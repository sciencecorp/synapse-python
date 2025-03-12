import time
from rich.table import Table


class PacketMonitor:
    def __init__(self):
        # Packet tracking
        self.packet_count = 0
        self.current_seq_number = None
        self.dropped_packets = 0
        self.out_of_order_packets = 0

        # Timing metrics
        self.start_time = None
        self.first_packet_time = None

        # Bandwidth tracking
        self.bytes_received = 0
        self.bytes_received_in_interval = 0
        self.bandwidth_samples = []
        self.last_bandwidth_time = None
        self.last_bytes_received = 0
        self.last_bandwidth = 0

        # Jitter tracking
        self.last_packet_time = None
        self.last_jitter = 0
        self.avg_jitter = 0

    def start_monitoring(self):
        """Initialize monitoring timers"""
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        self.last_bandwidth_time = self.start_time

    def process_packet(self, header, data, bytes_read):
        if not data:
            return False
        packet_received_time = time.time()
        # Record first packet time
        if self.packet_count == 0:
            self.first_packet_time = packet_received_time
            self.last_packet_time = packet_received_time
        else:
            # Calculate jitter
            interval = packet_received_time - self.last_packet_time
            # Update jitter using RFC 3550 algorithm (smoother than just max-min)
            # https://datatracker.ietf.org/doc/html/rfc3550#appendix-A.8
            if self.packet_count > 1:
                jitter_diff = abs(interval - self.last_jitter)
                self.avg_jitter += (jitter_diff - self.avg_jitter) / 16

            # Save current values for next calculation
            self.last_jitter = interval
            self.last_packet_time = packet_received_time

        # We got a new packet
        self.packet_count += 1
        self.bytes_received += bytes_read
        self.bytes_received_in_interval += bytes_read

        self.handle_sequence_number(header.seq_number)

        return True

    def sequence_distance(self, first, second):
        max_seq_num = 2**16 + 1
        # Force the inputs to a valid range
        first %= max_seq_num
        second %= max_seq_num

        # Get the distance in both directions (because it is a circle)
        forward = (first - second) % max_seq_num
        backward = (second - first) % max_seq_num

        # Get the shortest distance with the correct sign
        if forward <= backward:
            return forward
        else:
            return -1 * backward

    def handle_sequence_number(self, recv_seq_number):
        # Make sure the sequence number we get is in the range
        sequence_number = recv_seq_number % (2**16 + 1)

        if self.current_seq_number is None:
            self.current_seq_number = sequence_number
            return

        # we expect to see it monotonically increase
        expected_seq = (self.current_seq_number + 1) % (2**16 + 1)
        distance = self.sequence_distance(sequence_number, expected_seq)

        # Handle the case where it isn't what we expect
        if distance > 0:
            # Forward distance means packets were dropped
            self.dropped_packets += distance
        elif distance < 0:
            # negative distance means out of order packets
            self.out_of_order_packets += 1
        else:
            # We got a fine packet
            pass

        # Always update with the latest seq number
        self.current_seq_number = sequence_number

    def generate_stat_table(self) -> Table:
        table = Table()
        table.add_column("Runtime (sec)")
        table.add_column("Dropped (%)")
        table.add_column("Mbit/sec")
        table.add_column("Jitter (ms)")
        table.add_column("Out of Order")

        now = time.time()
        runtime_sec = now - self.start_time
        drop_percent = (self.dropped_packets / max(1, self.packet_count)) * 100.0
        dt_sec = now - self.last_bandwidth_time
        if dt_sec > 0:
            bytes_per_second = self.bytes_received_in_interval / dt_sec
            megabits_per_second = (bytes_per_second * 8) / 1_000_000
            self.last_bandwidth = megabits_per_second
        jitter_ms = self.avg_jitter * 1000
        table.add_row(
            f"{runtime_sec:.1f}",
            f"{self.dropped_packets}/{self.packet_count} ({drop_percent:.1f}%)",
            f"{self.last_bandwidth:.2f}",
            f"{jitter_ms:.1f}",
            f"{self.out_of_order_packets}",
        )
        return table
