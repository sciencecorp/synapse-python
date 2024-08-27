from enum import Enum
from queue import Queue
from typing import Optional 
from synapse.ndtp import packet


class ParseState(Enum):
    VERSION_DTYPE = 1
    TIMESTAMP = 2
    SEQ_NUM = 3
    CH_COUNT = 4
    DTYPE_CUSTOM = 5
    PAYLOAD = 6
    CRC = 7

class Depacketizer():
    def __init__ (self):
        self.parse_state = ParseState.VERSION_DTYPE
        self.tmp_packet = None

        self.packet_queue = Queue() 
        self.seq_num = 0

    def parse_bytes(self, packet_bytes: bytes):
        channels = {}

        i = 0
        while i  < len(packet_bytes):
            byte = packet_bytes[i]
            # print(f"idx {i} byte {byte}")
            if self.parse_state == ParseState.VERSION_DTYPE:
                # print(bytes[i:].hex())
                if (byte >> 6) != packet.VERSION:
                    raise Exception("Invalid version")

                dtype = byte & 0x3F
                if dtype == packet.DataType.NBS12.value:
                    self.tmp_packet = packet.NBS12Packet()
                elif dtype == packet.DataType.ST2.value:
                    self.tmp_packet = packet.ST2Packet()
                else:

                    raise Exception(f"Invalid data type {hex(dtype)}, {i}, {packet_bytes.hex()}")
                i += 1
                self.parse_state = ParseState.TIMESTAMP

            elif self.parse_state == ParseState.TIMESTAMP:
                self.tmp_packet.timestamp = int.from_bytes(packet_bytes[i:i+8])
                i += 8
                self.parse_state = ParseState.SEQ_NUM

            elif self.parse_state == ParseState.SEQ_NUM:
                self.tmp_packet.seq_num = byte
                if self.tmp_packet.seq_num != self.seq_num:
                    print(f"Seq num mismatch: {self.tmp_packet.seq_num} != {self.seq_num}")
                    self.seq_num = self.tmp_packet.seq_num
                if self.seq_num == 255:
                    self.seq_num = 0
                else:
                    self.seq_num += 1
                i += 1
                self.parse_state = ParseState.CH_COUNT

            elif self.parse_state == ParseState.CH_COUNT:
                self.tmp_packet.ch_count = int.from_bytes(packet_bytes[i:i+2])
                # print("Ch count: ", self.tmp_packet.ch_count)
                i += 2
                self.parse_state = ParseState.DTYPE_CUSTOM

            elif self.parse_state == ParseState.DTYPE_CUSTOM:
                self.tmp_packet.dtype_custom = int.from_bytes(packet_bytes[i:i+2])
                # print("Dtype custom: ", self.tmp_packet.dtype_custom)
                i += 2
                self.parse_state = ParseState.PAYLOAD

            elif self.parse_state == ParseState.PAYLOAD:
                payload_size = self.tmp_packet.payload_size()
                    
                payload_remaining = payload_size - len(self.tmp_packet.payload)
                # print(f"awawwaawaw {i} {payload_remaining} {len(packet_bytes)}")
                if i + payload_remaining > len(packet_bytes):
                    self.tmp_packet.payload += packet_bytes[i:]
                    break 
                else: 
                    # print(f"Payload size: {payload_size}")
                    self.tmp_packet.payload += packet_bytes[i:i+payload_remaining]
                # print(f"Payload: {self.tmp_packet.payload.hex()}")
                self.parse_state = ParseState.CRC
                self.packet_queue.put(self.tmp_packet)

                i += payload_remaining
            elif self.parse_state == ParseState.CRC:
                self.tmp_packet.crc16 = int.from_bytes(packet_bytes[i:i+2])
                if not self.tmp_packet.crc_check():
                    print(f"CRC check failed: {self.tmp_packet}")
                i += 2
                self.parse_state = ParseState.VERSION_DTYPE

    def get_packet(self) -> Optional[packet.Packet]:
        try:
            next_packet = self.packet_queue.get(block=False)
            return next_packet
        except:
            return False