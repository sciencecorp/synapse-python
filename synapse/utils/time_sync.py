import argparse
from dataclasses import dataclass
import logging
import random
import socket
import threading
import time
from typing import Union

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

class TimeSyncClient:
    def __init__(self, host: str, port: int, config: TimeSyncConfig = TimeSyncConfig(), logger: Union[logging.Logger, None] = None):
        self.client_id = self.generate_client_id()
        self.host = host
        self.port = port
        self.running = False
        self.sequence_number = 0
        self.config = config or TimeSyncConfig()
        self.current_rtts = [TimeSyncEstimate() for _ in range(self.config.max_sync_packets)]
        self.latest_offset_ns = 0
        self.socket = None
        self.sync_thread = None
        self.receive_thread = None

        self.logger = logging.getLogger("time-sync") if logger is None else logger
        
        self.logger.debug(f"TimeSyncClient initialized with client_id: {self.client_id}")

    def generate_client_id(self) -> int:
        return random.randint(0, 2**32 - 1)

    def start(self) -> bool:
        if self.running:
            return True

        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('0.0.0.0', 0))
        self.socket.connect((self.host, self.port))
        
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()

        self.sync_thread = threading.Thread(target=self._sync_loop)
        self.sync_thread.daemon = True
        self.sync_thread.start()

        self.logger.info(f"TimeSyncClient started with client_id: {self.client_id} and host: {self.host} and port: {self.port}")
        
        return True

    def stop(self):
        if not self.running:
            return

        self.running = False
        if self.socket:
            self.socket.close()
        
        if self.sync_thread:
            self.sync_thread.join(timeout=1.0)
        if self.receive_thread:
            self.receive_thread.join(timeout=1.0)

    def _sync_loop(self):
        while self.running:
            self._send_next_sync_packet()

    def _receive_loop(self):
        while self.running:
            try:
                data, _ = self.socket.recvfrom(self.config.max_packet_size)
                self.handle_response(data)
            except (socket.error, Exception) as e:
                if self.running:
                    self.logger.error(f"Error receiving data: {e}")

    def _send_next_sync_packet(self):
        if self.sequence_number >= self.config.max_sync_packets:
            self.update_estimate()
            self.logger.info(f"Synced with {self.sequence_number} packets, updating estimate - current offset: {self.latest_offset_ns} ns")
            time.sleep(self.config.sync_interval_s)
            return

        if self.sequence_number == 0:
            self.logger.info(f"Sending sync packets...")

        request = TimeSyncPacket()
        request.client_id = self.client_id
        request.sequence = self.sequence_number
        request.client_send_time_ns = int(time.time_ns())
        
        try:
            self.socket.send(request.SerializeToString())
        except Exception as e:
            self.logger.error(f"Error sending packet: {e}")
        finally:
            time.sleep(self.config.send_delay_ms / 1000.0)

    def handle_response(self, data: bytes):
        now_ns = time.time_ns()

        try:
            response = TimeSyncPacket()
            response.ParseFromString(data)
            response.client_receive_time_ns = now_ns

            if response.client_id != self.client_id:
                return

            estimate = get_time_sync_estimate(response)
            self.current_rtts[self.sequence_number] = estimate
            self.sequence_number += 1

        except Exception as e:
            self.logger.error(f"Error processing response: {e}")

    def update_estimate(self):
        if not self.current_rtts:
            return

        best_estimate = min(self.current_rtts[:self.sequence_number], 
                          key=lambda x: x.rtt_ns)
        
        self.latest_offset_ns = best_estimate.offset_ns
        self.sequence_number = 0
        self.current_rtts = [TimeSyncEstimate() for _ in range(self.config.max_sync_packets)]

    def get_offset_ns(self) -> int:
        return self.latest_offset_ns

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

    from synapse.utils.logging import init_logging
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
