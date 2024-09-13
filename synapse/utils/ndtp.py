import struct
from dataclasses import dataclass
from typing import List
from synapse.api.datatype_pb2 import DataType


NDTPHeaderStruct = struct.Struct("<IIQH")
NDTP_HEADER_SIZE_BYTES = NDTPHeaderStruct.size

MAGIC_HEADER = 0xC0FFEE00

def to_bytes(values: List[int], bit_width: int) -> bytes:
    if bit_width <= 0:
        raise ValueError("bit width must be > 0")
    
    result = bytearray()
    current_byte = 0
    bits_in_current_byte = 0

    for value in values:
        if value < 0 or value >= (1 << bit_width):
            raise ValueError(f"alue {value} doesn't fit in {bit_width} bits")

        remaining_bits = bit_width
        while remaining_bits > 0:
            if bits_in_current_byte == 8:
                result.append(current_byte)
                current_byte = 0
                bits_in_current_byte = 0

            bits_to_add = min(8 - bits_in_current_byte, remaining_bits)
            shift = remaining_bits - bits_to_add
            mask = ((1 << bits_to_add) - 1) << shift
            bits = (value & mask) >> shift

            current_byte |= bits << (8 - bits_in_current_byte - bits_to_add)
            bits_in_current_byte += bits_to_add
            remaining_bits -= bits_to_add

    if bits_in_current_byte > 0:
        result.append(current_byte)

    return bytes(result)
'''
Pack a list of integers into a byte array, using the specified bit width for each value.

A 'count' parameter can be used if the number of values and their bit widths do not pack neatly into whole bytes.
'''
def to_ints(data: bytes, bit_width: int, count: int = 0) -> List[int]:
    if bit_width <= 0:
        raise ValueError("bit width must be > 0")

    result = []
    current_value = 0
    bits_in_current_value = 0
    mask = (1 << bit_width) - 1

    for byte in data:
        for bit_index in range(7, -1, -1):
            bit = (byte >> bit_index) & 1
            current_value = (current_value << 1) | bit
            bits_in_current_value += 1

            if bits_in_current_value == bit_width:
                result.append(current_value & mask)
                current_value = 0
                bits_in_current_value = 0

    if bits_in_current_value == bit_width:
        result.append(current_value & mask)

    elif bits_in_current_value != 0 and count == 0:
        raise ValueError(f"{bits_in_current_value} bits left over, not enough to form a complete value of bit width {bit_width}")
    
    if count > 0:
        result = result[:count]
    
    return result

@dataclass
class NDTPPayloadBroadband:
    channel_id: int
    sample_count: int
    bit_width: int
    channel_data: List[int]

    Header = struct.Struct("<IIB")

    def pack(self):
        payload = bytes()
        payload += NDTPPayloadBroadband.Header.pack(
            self.channel_id,
            self.sample_count,
            self.bit_width
        )
        payload += to_bytes(self.channel_data, self.bit_width)
        return payload
    
    @staticmethod
    def unpack(data: bytes):
        h_size = NDTPPayloadBroadband.Header.size
        channel_id, sample_count, bit_width = NDTPPayloadBroadband.Header.unpack(data[:h_size])
        channel_data = to_ints(data[h_size:], bit_width, sample_count)
        return NDTPPayloadBroadband(
            channel_id,
            sample_count,
            bit_width,
            channel_data
        )

@dataclass
class NDTPPayloadSpiketrain:
    BIT_WIDTH = 2
    spike_counts: List[int]

    def pack(self):
        return to_bytes(self.spike_counts, self.BIT_WIDTH)
    
    @staticmethod
    def unpack(data: bytes):
        return NDTPPayloadSpiketrain(to_ints(data, NDTPPayloadSpiketrain.BIT_WIDTH))

def deserialize_spiketrain(t0, ch_count, data):
    spike_data = data[NDTP_HEADER_SIZE_BYTES:]
    return [t0, [struct.unpack("B", spike_data[i : i + 1])[0] for i in range(ch_count)]]


@dataclass
class NDTPHeader:
    data_type: int
    timestamp: int
    seq_number: int

    def pack(self):
        return NDTPHeaderStruct.pack(
            MAGIC_HEADER,
            self.data_type,
            self.timestamp,
            self.seq_number
        )

    @staticmethod
    def unpack(data: bytes):
        if len(data) < NDTPHeaderStruct.size:
            raise ValueError(f"Invalid header size {len(data)}: expected {NDTPHeaderStruct.size} (got {len(data)})")

        magic_header = struct.unpack("<I", data[:4])[0]
        if magic_header != MAGIC_HEADER:
            raise ValueError(f"Invalid magic header {magic_header}: expected {hex(MAGIC_HEADER)}, got {hex(magic_header)}")

        _, data_type, timestamp, seq_number = NDTPHeaderStruct.unpack(data)
        return NDTPHeader(data_type, timestamp, seq_number)

@dataclass
class NDTPMessage:
    header: NDTPHeader
    payload: any
    crc32: int

    def pack(self):
        header = self.header.pack()
        payload = self.payload.pack() if self.payload else bytes()
        crc32 = struct.pack("<I", self.crc32)

        return header + payload + crc32

    @staticmethod
    def unpack(data: bytes):
        header = NDTPHeader.unpack(data[:NDTP_HEADER_SIZE_BYTES])
        crc32 = struct.unpack("<I", data[-4:])[0]

        pbytes = data[NDTP_HEADER_SIZE_BYTES:-4]
        pdtype = header.data_type

        if pdtype == DataType.kBroadband:
            payload = NDTPPayloadBroadband.unpack(pbytes)
        elif pdtype == DataType.kSpiketrain:
            payload = NDTPPayloadSpiketrain.unpack(pbytes)
        else:
            raise ValueError(f"unknown data type {pdtype}")
        
        return NDTPMessage(header, payload, crc32)

