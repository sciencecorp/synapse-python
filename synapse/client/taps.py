import logging
import time
import zmq
from typing import Optional, Generator

from synapse.api.query_pb2 import QueryRequest
from synapse.api.status_pb2 import StatusCode
from synapse.api.tap_pb2 import TapType


class Tap(object):
    def __init__(self, uri, verbose=False):
        """Initialize a Tap client to connect to the Synapse device.

        Args:
            uri (str): The URI of the Synapse device.
            verbose (bool, optional): Whether to enable verbose logging. Defaults to False.
        """
        self.uri = uri
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        # ZMQ context (will be initialized upon connection)
        self.zmq_context = None
        self.zmq_socket = None
        self.connected_tap = None

    def list_taps(self):
        """List all available taps on the device.

        Returns:
            list: List of TapConnection objects.
        """
        from synapse.client.device import Device

        device = Device(self.uri, self.verbose)

        request = QueryRequest()
        request.query_type = QueryRequest.kListTaps
        request.list_taps_query.SetInParent()

        response = device.query(request)

        if not response or response.status.code != StatusCode.kOk:
            self.logger.error(
                f"Failed to list taps: {response.status.message if response else 'No response'}"
            )
            return []

        return response.list_taps_response.taps

    def connect(self, name: str) -> bool:
        """Connect to a specific tap by name.

        Args:
            name (str): The name of the tap to connect to.

        Returns:
            bool: True if connected successfully, False otherwise.
        """
        taps = self.list_taps()

        # Find the tap with the specified name
        selected_tap = None
        for tap in taps:
            if tap.name == name:
                selected_tap = tap
                break

        if not selected_tap:
            self.logger.error(f"Tap '{name}' not found")
            return False

        # Store the connected tap
        self.connected_tap = selected_tap

        # Initialize ZMQ context and socket
        self.zmq_context = zmq.Context()

        # Create appropriate socket type based on tap type from the selected tap
        if selected_tap.tap_type == TapType.TAP_TYPE_CONSUMER:
            # For consumer taps, we need to publish data TO the tap
            self.zmq_socket = self.zmq_context.socket(zmq.PUB)
        else:
            # For producer taps (or unspecified), we need to subscribe and listen FROM the tap
            self.zmq_socket = self.zmq_context.socket(zmq.SUB)

        # Optimize ZMQ for high-throughput data
        # Increase receive buffer size significantly for high-speed data
        self.zmq_socket.setsockopt(
            zmq.RCVHWM, 10000
        )  # High water mark - buffer up to 10K messages
        self.zmq_socket.setsockopt(zmq.RCVBUF, 16 * 1024 * 1024)  # 16MB receive buffer

        # Set TCP keepalive for connection stability
        self.zmq_socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.zmq_socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)

        # Replace the endpoint with our device URI if needed
        endpoint = selected_tap.endpoint
        if "://" in endpoint:
            # Extract the protocol and port
            protocol, address = endpoint.split("://")
            _, port = address.split(":")

            # Use the device URI with the same port
            endpoint = f"{protocol}://{self.uri.split(':')[0]}:{port}"

        try:
            self.zmq_socket.connect(endpoint)

            # Reduce connection wait time to minimize startup delay
            self.logger.info("Connecting to tap...")
            time.sleep(0.1)  # Reduced from 1 second

            # Only set subscription options for subscriber sockets
            if selected_tap.tap_type != TapType.TAP_TYPE_CONSUMER:
                self.zmq_socket.setsockopt(zmq.SUBSCRIBE, b"")

            return True
        except zmq.ZMQError as e:
            self.logger.error(f"Failed to connect to tap: {e}")
            self._cleanup()
            return False

    def read(self, timeout_ms: int = 1000) -> Optional[bytes]:
        """Read raw data from the tap with timeout.

        Args:
            timeout_ms (int, optional): Timeout in milliseconds. Defaults to 1000.

        Returns:
            Optional[bytes]: Raw message data or None if timeout/error.
        """
        if not self.zmq_socket:
            self.logger.error("Not connected to any tap")
            return None

        try:
            # Set socket timeout
            self.zmq_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)

            # Receive data (will timeout if no data available)
            return self.zmq_socket.recv()
        except zmq.Again:
            # Timeout occurred
            return None
        except zmq.ZMQError as e:
            self.logger.error(f"Error receiving message: {e}")
            return None

    def send(self, data: bytes) -> bool:
        """Send raw data to the tap (only works for consumer taps with PUB socket).

        Args:
            data (bytes): Raw message data to send.

        Returns:
            bool: True if sent successfully, False otherwise.
        """
        if not self.zmq_socket:
            self.logger.error("Not connected to any tap")
            return False

        if (
            not self.connected_tap
            or self.connected_tap.tap_type != TapType.TAP_TYPE_CONSUMER
        ):
            self.logger.error("Send is only available for consumer taps")
            return False

        try:
            self.zmq_socket.send(data)
            return True
        except zmq.ZMQError as e:
            self.logger.error(f"Error sending message: {e}")
            return False

    def stream(self, timeout_ms: int = 100) -> Generator[bytes, None, None]:
        """Stream raw data from the tap with optimizations for high-throughput data.

        Args:
            timeout_ms (int, optional): Timeout between messages in milliseconds. Defaults to 100.

        Yields:
            Generator[bytes, None, None]: Stream of raw message data.
        """
        if not self.zmq_socket:
            self.logger.error("Not connected to any tap")
            return

        # Set a shorter timeout for high-frequency data
        self.zmq_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)

        try:
            while True:
                try:
                    # Use non-blocking receive with DONTWAIT for maximum throughput
                    data = self.zmq_socket.recv(zmq.DONTWAIT)
                    yield data
                except zmq.Again:
                    # No data available right now, yield control briefly
                    time.sleep(0.0001)  # 0.1ms sleep to prevent busy waiting
                    continue
        except KeyboardInterrupt:
            self.logger.info("Stream interrupted")
        except zmq.ZMQError as e:
            self.logger.error(f"Error streaming messages: {e}")
        finally:
            # Don't close the socket here, let the user call disconnect()
            pass

    def stream_batch(
        self, batch_size: int = 10, timeout_ms: int = 100
    ) -> Generator[list, None, None]:
        """Stream data in batches for improved throughput.

        Args:
            batch_size (int, optional): Number of messages to batch together. Defaults to 10.
            timeout_ms (int, optional): Timeout for each receive operation. Defaults to 100.

        Yields:
            Generator[list, None, None]: Batches of raw message data.
        """
        if not self.zmq_socket:
            self.logger.error("Not connected to any tap")
            return

        self.zmq_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)

        batch = []
        try:
            while True:
                try:
                    data = self.zmq_socket.recv(zmq.DONTWAIT)
                    batch.append(data)

                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                except zmq.Again:
                    # No data available, yield partial batch if any
                    if batch:
                        yield batch
                        batch = []
                    time.sleep(0.0001)
                    continue
        except KeyboardInterrupt:
            self.logger.info("Stream interrupted")
            if batch:
                yield batch
        except zmq.ZMQError as e:
            self.logger.error(f"Error streaming messages: {e}")
            if batch:
                yield batch

    def disconnect(self):
        """Disconnect from the tap."""
        self._cleanup()

    def _cleanup(self):
        """Clean up ZMQ resources."""
        if self.zmq_socket:
            self.zmq_socket.close()
            self.zmq_socket = None

        if self.zmq_context:
            self.zmq_context.term()
            self.zmq_context = None

        self.connected_tap = None
