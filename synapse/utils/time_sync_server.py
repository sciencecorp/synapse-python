import asyncio
import logging
import time
from typing import Optional

from synapse.api.time_pb2 import TimeSyncPacket
from synapse.utils.log import init_logging

MAX_PACKET_SIZE = 1024

class TimeSyncServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.transport = None
        self._logger = logger if logger else logging.getLogger('time-sync-server')
        self._running = False

    def connection_made(self, transport):
        self._logger.debug("Server started")
        self.transport = transport
        self._running = True

    def connection_lost(self, exc):
        self._logger.debug("Server stopped")
        self._running = False
        self.transport = None
        if exc:
            self._logger.error(f"Connection lost: {exc}")

    def datagram_received(self, data, addr):
        """Handle incoming time sync packets."""
        self._logger.info(f"Received data from {addr}")
        try:
            # Get receive time as soon as possible
            receive_time_ns = time.time_ns()
            
            request = TimeSyncPacket()
            if not request.ParseFromString(data):
                self._logger.error("Received invalid packet")
                return

            self._logger.debug(f"Received sync packet from {addr}: {request}")

            response = TimeSyncPacket()
            response.client_id = request.client_id
            response.sequence = request.sequence
            response.client_send_time_ns = request.client_send_time_ns
            response.server_receive_time_ns = receive_time_ns
            response.server_send_time_ns = time.time_ns()

            response_data = response.SerializeToString()
            if response_data:
                self._logger.info(f"Sending response to {addr} - client_id: {response.client_id}, sequence: {response.sequence}")
                self.transport.sendto(response_data, addr)
                self._logger.debug(f"Sent {len(response_data)} bytes to {addr}")
            else:
                self._logger.error("Failed to serialize response packet")

        except Exception as e:
            self._logger.error(f"Error processing packet: {e}", exc_info=True)

class TimeSyncServer:
    """
    UDP server that responds to time sync packets with server timestamps.
    """
    def __init__(self, host: str = "0.0.0.0", port: int = 52340, logger: Optional[logging.Logger] = None):
        self._host = host
        self._port = port
        self._logger = logger if logger else logging.getLogger('time-sync-server')
        self._transport = None
        self._protocol = None
        self._running = False

    def start(self) -> bool:
        """Start the time sync server."""
        if self._running:
            return True

        try:
            loop = asyncio.get_event_loop()
            
            self._logger.info(f"Starting time sync server on {self._host}:{self._port}")
            
            transport, protocol = loop.run_until_complete(
                loop.create_datagram_endpoint(
                    lambda: TimeSyncServerProtocol(self._logger),
                    local_addr=(self._host, self._port),
                    reuse_port=True
                )
            )
            
            self._transport = transport
            self._protocol = protocol
            self._running = True
            
            self._logger.info(f"Time sync server listening on {self._host}:{self._port}")
            return True
            
        except Exception as e:
            self._logger.error(f"Error starting time sync server: {e}")
            return False

    def stop(self) -> bool:
        """Stop the time sync server."""
        if not self._running:
            return False

        try:
            if self._transport:
                self._transport.close()
            self._transport = None
            self._protocol = None
            self._running = False
            self._logger.info("Time sync server stopped")
            return True
            
        except Exception as e:
            self._logger.error(f"Error stopping time sync server: {e}")
            return False

if __name__ == "__main__":
    import argparse
    
    init_logging(level=logging.DEBUG)
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=52340)
    args = parser.parse_args()

    server = TimeSyncServer(args.host, args.port)
    server.start()

    loop = asyncio.get_event_loop()
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        loop.close()
        logging.info("Done.")
