#!/usr/bin/env python3
import unittest

from synapse.utils.packet_monitor import PacketMonitor


class PacketMonitorTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_handle_sequence_number(self):
        packet_monitor = PacketMonitor()

        # Start with zero
        packet_monitor.handle_sequence_number(0)
        self.assertEqual(packet_monitor.current_seq_number, 0)

        packet_monitor.handle_sequence_number(1)
        self.assertEqual(packet_monitor.current_seq_number, 1)

        # Dropped a packet
        packet_monitor.handle_sequence_number(3)
        self.assertEqual(packet_monitor.current_seq_number, 3)
        self.assertEqual(packet_monitor.dropped_packets, 1)

        # Dropped a bunch of packets (we expect to be at 4, but we are at 1000)
        # Dropped packets is 1000 - 4 + the previous dropped
        packet_monitor.handle_sequence_number(1000)
        self.assertEqual(packet_monitor.current_seq_number, 1000)
        self.assertEqual(packet_monitor.dropped_packets, 1 + (1000 - 4))

    def test_handle_wrap_around(self):
        packet_monitor = PacketMonitor()

        # Start near the threshold
        start_index = (2**16) - 1
        packet_monitor.handle_sequence_number(start_index)
        self.assertEqual(packet_monitor.dropped_packets, 0)
        self.assertEqual(packet_monitor.current_seq_number, start_index)

        # Drop some packets
        packet_monitor.handle_sequence_number(10)
        self.assertEqual(packet_monitor.dropped_packets, (2**16 - start_index) + 10)
        self.assertEqual(packet_monitor.current_seq_number, 10)
        dropped_so_far = packet_monitor.dropped_packets

        # Continue
        packet_monitor.handle_sequence_number(100)
        self.assertEqual(packet_monitor.dropped_packets, dropped_so_far + (100 - 11))
        self.assertEqual(packet_monitor.current_seq_number, 100)

    def test_handle_ooo(self):
        packet_monitor = PacketMonitor()
        packet_monitor.handle_sequence_number(10)
        self.assertEqual(packet_monitor.dropped_packets, 0)
        self.assertEqual(packet_monitor.current_seq_number, 10)
        self.assertEqual(packet_monitor.out_of_order_packets, 0)

        packet_monitor.handle_sequence_number(9)
        self.assertEqual(packet_monitor.dropped_packets, 0)
        self.assertEqual(packet_monitor.current_seq_number, 9)
        self.assertEqual(packet_monitor.out_of_order_packets, 1)

        packet_monitor.handle_sequence_number(11)
        self.assertEqual(packet_monitor.dropped_packets, 1)
        self.assertEqual(packet_monitor.current_seq_number, 11)
        self.assertEqual(packet_monitor.out_of_order_packets, 1)


if __name__ == "__main__":
    unittest.main()
