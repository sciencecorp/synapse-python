import argparse
from dataclasses import dataclass
import logging
import random
import socket
import threading
import time
from typing import Tuple, Union, List

from synapse.api.time_pb2 import TimeSyncPacket

@dataclass
class TimeSyncConfig:
    max_packet_size: int = 1024
    max_sync_packets: int = 12
    send_delay_ms: int = 200
    timeout_s: float = 1.0
    sync_interval_s: int = 5

@dataclass
class TimeSyncEstimate:
    rtt_ns = 0
    offset_ns = 0


def calculate_root_dispersion(samples: List[TimeSyncEstimate], best_offset_ns: int) -> Union[int, None]:
    if len(samples) == 0:
        return 0
        
    min_rtt_sample = None
    for sample in samples:
        if sample.rtt_ns <= 0:
            continue
        if min_rtt_sample is None or sample.rtt_ns < min_rtt_sample.rtt_ns:
            min_rtt_sample = sample

    if min_rtt_sample is None:
        return None
    
    squared_deviations = [(sample.offset_ns - best_offset_ns) ** 2 for sample in samples]
    std_dev_ns = int((sum(squared_deviations) / len(samples)) ** 0.5)
    
    root_dispersion_ns = (min_rtt_sample.rtt_ns // 2) + (2 * std_dev_ns)
    return root_dispersion_ns

def get_time_sync_estimate(packet: TimeSyncPacket) -> TimeSyncEstimate:
    server_calculation_time_ns = packet.server_send_time_ns - packet.server_receive_time_ns

    round_trip_ns = (packet.client_receive_time_ns - packet.client_send_time_ns) - server_calculation_time_ns

    # See NTP calculation:
    # https://en.wikipedia.org/wiki/Network_Time_Protocol#Clock_synchronization_algorithm
    send_offset_ns = packet.server_receive_time_ns - packet.client_send_time_ns
    recv_offset_ns = packet.server_send_time_ns - packet.client_receive_time_ns
    calculated_offset_ns = (send_offset_ns + recv_offset_ns) // 2

    estimate = TimeSyncEstimate()
    estimate.rtt_ns = round_trip_ns
    estimate.offset_ns = calculated_offset_ns
    return estimate

class OffsetEstimator:
    def __init__(self, window_size: int = 120):
        self._window_size = window_size
        self._best_offset_ns = 0
        self._samples: List[TimeSyncEstimate] = []

    def add_sample(self, estimate: TimeSyncEstimate):
        self._samples.append(estimate)
        if len(self._samples) > self._window_size:
            self._samples.pop(0)

        self._update()

    def get_offset_ns(self) -> int:
        return self._best_offset_ns
    
    def root_dispersion_ns(self) -> Union[int, None]:
        return calculate_root_dispersion(self._samples, self._best_offset_ns)

    def _update(self):
        if len(self._samples) == 0:
            return
        
        sorted_samples = sorted(self._samples, key=lambda x: x.rtt_ns)
        self._best_offset_ns = sorted_samples[0].offset_ns

class TimeSyncClient:
    def __init__(self, host: str, port: int, config: TimeSyncConfig = TimeSyncConfig(), logger: Union[logging.Logger, None] = None):
        self.sequence_number = 0
        self.client_id = self._generate_client_id()
        self.host = host
        self.port = port
        self.running = False
        self.config = config or TimeSyncConfig()
        self.offset_estimator = OffsetEstimator()
        self.current_rtts = [TimeSyncEstimate() for _ in range(self.config.max_sync_packets)]
        self.latest_offset_ns = 0
        self.last_sync_time_ns = (0, 0)
        self.socket = None
        self.worker_thread = None
        self.logger = logging.getLogger("time-sync") if logger is None else logger

        self.logger.debug(f"TimeSyncClient initialized with client_id: {self.client_id} and host: {self.host} and port: {self.port}")
        
    def _generate_client_id(self) -> int:
        return random.randint(0, 2**32 - 1)

    def start(self) -> bool:
        if self.running:
            return True

        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('0.0.0.0', 0))
        self.socket.connect((self.host, self.port))
        self.socket.settimeout(self.config.timeout_s)
        
        self.worker_thread = threading.Thread(target=self._worker_thread)
        self.worker_thread.daemon = True
        self.worker_thread.start()

        self.logger.info("TimeSyncClient started")
        return True

    def stop(self):
        if not self.running:
            return

        self.running = False
        if self.socket:
            self.socket.close()
        
        if self.worker_thread:
            self.worker_thread.join(timeout=1.0)

    def _worker_thread(self):
        try:
            self._send_next_sync_packet()
            while self.running:
                try:
                    data, _ = self.socket.recvfrom(self.config.max_packet_size)
                    self._handle_response(data)
                except socket.timeout:
                    self.logger.debug("Timeout waiting for response")
                    self._schedule_next_sync()
                except socket.error as e:
                    if self.running:
                        self.logger.error(f"Socket error: {e}")
                        self._schedule_next_sync()
        except Exception as e:
            self.logger.error(f"Worker thread error: {e}")
            self.running = False

    def _schedule_next_sync(self):
        if self.sequence_number >= self.config.max_sync_packets - 1:
            self._update_estimate()
            self.logger.debug(f"Synced with {self.config.max_sync_packets} packets, updating estimate - current offset: {self.latest_offset_ns} ns")
            time.sleep(self.config.sync_interval_s)
            if self.running:
                self._send_next_sync_packet()
    
        else:
            time.sleep(self.config.send_delay_ms / 1000.0)
            if self.running:
                self.sequence_number += 1
                self._send_next_sync_packet()

    def _send_next_sync_packet(self):
        if not self.running:
            return

        if self.sequence_number == 0:
            self.logger.debug("Sending sync packets...")

        request = TimeSyncPacket()
        request.client_id = self.client_id
        request.sequence = self.sequence_number
        request.client_send_time_ns = int(time.time_ns())
        
        try:
            self.logger.debug(f"Sending sync packet {self.sequence_number} / {self.config.max_sync_packets}")
            self.socket.send(request.SerializeToString())
        except Exception as e:
            self.logger.error(f"Error sending packet: {e}")
            self._schedule_next_sync()

    def _handle_response(self, data: bytes):
        now_ns = time.time_ns()

        response = None
        try:
            response = TimeSyncPacket()
            response.ParseFromString(data)
            response.client_receive_time_ns = now_ns

            if response.client_id != self.client_id:
                self.logger.warning(f"Received sync packet from {response.client_id}, but expected {self.client_id}")
                return

            estimate = get_time_sync_estimate(response)

            if self.sequence_number >= self.config.max_sync_packets:
                self.logger.warning(f"Received sync packet {self.sequence_number} / {self.config.max_sync_packets}, but max is {self.config.max_sync_packets}")
                return

            self.current_rtts[self.sequence_number] = estimate

            self.last_sync_time_ns = (time.time_ns(), self.time_ns())

        except Exception as e:
            self.logger.error(f"Error processing response: {e}")
            return

        finally:
            self._schedule_next_sync()

    def _update_estimate(self):
        if not self.current_rtts:
            return

        best_estimate = None
        for estimate in self.current_rtts[:min(self.sequence_number + 1, len(self.current_rtts))]:
            if estimate.rtt_ns <= 0:
                continue
            if best_estimate is None or estimate.rtt_ns < best_estimate.rtt_ns:
                best_estimate = estimate

        if best_estimate is not None and best_estimate.rtt_ns > 0:
            self.offset_estimator.add_sample(best_estimate)
            self.latest_offset_ns = self.offset_estimator.get_offset_ns()
            root_dispersion_ns = self.offset_estimator.root_dispersion_ns()

            self.logger.debug(f"Updated estimate - current offset: {self.latest_offset_ns / 1e6} ms, dispersion: {root_dispersion_ns / 1e6 if root_dispersion_ns is not None else 'N/A'} ms")

        self.sequence_number = 0
        self.current_rtts = [TimeSyncEstimate() for _ in range(self.config.max_sync_packets)]

    def get_offset_ns(self) -> int:
        return self.latest_offset_ns

    def get_last_sync_time_ns(self) -> Tuple[int, int]:
        """
        Returns a tuple of the last sync time in ns as [client's clock from time.time_ns(), synced clock from self.time_ns()]
        """
        return self.last_sync_time_ns

    def time_ns(self) -> int:
        return time.time_ns() + self.latest_offset_ns
    
    def time(self) -> float:
        return time.time() + self.latest_offset_ns / 1e9

def main():
    parser = argparse.ArgumentParser(description='Time synchronization client')
    parser.add_argument('--host', type=str, default='localhost',
                       help='Time sync server host (default: localhost)')
    parser.add_argument('--port', type=int, default=52340,
                       help='Time sync server port (default: 52340)')
    args = parser.parse_args()

    from synapse.utils.log import init_logging
    init_logging(level=logging.DEBUG)

    client = TimeSyncClient(args.host, args.port)
    try:
        client.start()
        while True:
            time.sleep(1)
            offset = client.get_offset_ns()
            logging.info(f"Current offset: {offset} ns")
    except KeyboardInterrupt:
        logging.info("\nShutting down client...")
    finally:
        client.stop()

if __name__ == '__main__':
    main()
