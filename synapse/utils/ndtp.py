from dataclasses import dataclass
import struct
import math
from typing import List, Tuple
from synapse.api.datatype_pb2 import DataType


NDTP_VERSION = 1


def convert_to_hex(byte_string):
    # Convert the input string to bytes if it's not already
    if isinstance(byte_string, str):
        byte_string = byte_string.encode("latin-1")

    # Convert each byte to its two-character hexadecimal representation with '\x' prefix
    hex_values = ["\\x" + f"{b:02x}" for b in byte_string]

    # Join the hex values into a single string
    formatted_hex = "".join(hex_values)

    return formatted_hex


def bytes_to_binary(data: bytes, start_bit: int) -> str:
    binary_string = ""
    for byte in data:
        binary_string += bin(byte)[2:].zfill(8)
    # add space after every 8 bits
    binary_string = binary_string[start_bit:]
    binary_string = " ".join(
        [binary_string[i : i + 8] for i in range(0, len(binary_string), 8)]
    )
    return binary_string


"""
Packs a list of integers into a byte array, using the specified bit width for each value.

Can append to an existing byte array, and will correctly handle the case where
the end of the existing array is not byte aligned (and may contain a partial byte at the end).
"""


def to_bytes(
    values: List[int],
    bit_width: int,
    existing: bytearray = None,
    writing_bit_offset: int = 0,
    signed: bool = False,
) -> Tuple[bytearray, int]:
    if bit_width <= 0:
        raise ValueError("bit width must be > 0")

    truncate_bytes = writing_bit_offset // 8
    writing_bit_offset = writing_bit_offset % 8

    result = existing[truncate_bytes:] if existing is not None else bytearray()
    continue_last = existing is not None and writing_bit_offset > 0
    current_byte = result[-1] if result and writing_bit_offset > 0 else 0
    bits_in_current_byte = writing_bit_offset

    for value in values:
        if signed:
            min_value = -(1 << (bit_width - 1))
            max_value = (1 << (bit_width - 1)) - 1
            if value < min_value or value > max_value:
                raise ValueError(
                    f"signed value {value} doesn't fit in {bit_width} bits"
                )
            # Convert to two's complement representation
            if value < 0:
                value = (1 << bit_width) + value
        else:
            if value < 0:
                raise ValueError("unsigned packing specified, but value is negative")

            if value >= (1 << bit_width):
                raise ValueError(
                    f"unsigned value {value} doesn't fit in {bit_width} bits"
                )

        remaining_bits = bit_width
        while remaining_bits > 0:
            available_bits = 8 - bits_in_current_byte
            bits_to_write = min(available_bits, remaining_bits)

            shift = remaining_bits - bits_to_write
            bits_to_add = (value >> shift) & ((1 << bits_to_write) - 1)

            current_byte |= bits_to_add << (available_bits - bits_to_write)

            remaining_bits -= bits_to_write
            bits_in_current_byte += bits_to_write

            if bits_in_current_byte == 8:
                if continue_last:
                    result[-1] = current_byte
                    continue_last = False
                else:
                    result.append(current_byte)
                current_byte = 0
                bits_in_current_byte = 0

    if bits_in_current_byte > 0:
        result.append(current_byte)

    return result, bits_in_current_byte


"""
Parses a list of integers from a byte array, using the specified bit width for each value.

A 'count' parameter can be used if the expected number of values does not pack neatly into whole byte, with their given bit_width.
"""


import math


def to_ints(
    data: bytes,
    bit_width: int,
    count: int = 0,
    start_bit: int = 0,
    signed: bool = False,
) -> Tuple[List[int], int, bytes]:
    if bit_width <= 0:
        raise ValueError("bit width must be > 0")

    truncate_bytes = start_bit // 8
    start_bit = start_bit % 8

    data = data[truncate_bytes:]

    if count > 0 and len(data) < math.ceil(bit_width * count / 8):
        raise ValueError(
            f"insufficient data for {count} x {bit_width} bit values (expected {math.ceil(bit_width * count / 8)} bytes, given {len(data)} bytes)"
        )

    values = []
    current_value = 0
    bits_in_current_value = 0
    mask = (1 << bit_width) - 1
    total_bits_read = 0

    for byte_index, byte in enumerate(data):
        start = start_bit if byte_index == 0 else 0
        for bit_index in range(7 - start, -1, -1):
            bit = (byte >> bit_index) & 1
            current_value = (current_value << 1) | bit
            bits_in_current_value += 1
            total_bits_read += 1

            if bits_in_current_value == bit_width:
                if signed and (current_value & (1 << (bit_width - 1))):
                    current_value = current_value - (1 << bit_width)
                else:
                    current_value = current_value & mask
                values.append(current_value)
                current_value = 0
                bits_in_current_value = 0

            if count > 0 and len(values) == count:
                end_bit = start_bit + total_bits_read
                return values, end_bit, data

    if bits_in_current_value > 0:
        if bits_in_current_value == bit_width:
            if signed and (current_value & (1 << (bit_width - 1))):
                current_value = current_value - (1 << bit_width)
            else:
                current_value = current_value & mask
            values.append(current_value)
        elif count == 0:
            raise ValueError(
                f"{bits_in_current_value} bits left over, not enough to form a complete value of bit width {bit_width}"
            )

    if count > 0:
        values = values[:count]

    end_bit = start_bit + total_bits_read
    return values, end_bit, data


@dataclass
class NDTPPayloadBroadband:
    @dataclass
    class ChannelData:
        channel_id: int  # 24-bit
        channel_data: List[int]  # bit_width * num_samples bits

    signed: bool
    bit_width: int
    sample_rate: int
    channels: List[ChannelData]

    def pack(self):
        n_channels = len(self.channels)

        payload = bytearray()

        # first bit of the payload is the signed bool
        # remaining 7 bits are the bit width
        payload += struct.pack(
            "<B", ((self.bit_width & 0x7F) << 1) | (1 if self.signed else 0)
        )

        payload += struct.pack(
            "<BBB",
            (n_channels >> 16) & 0xFF,
            (n_channels >> 8) & 0xFF,
            n_channels & 0xFF,
        )

        payload += struct.pack("<H", self.sample_rate)

        # packed data is not byte aligned, we do not add padding, so we need to pack the data manually
        b_offset = 0
        for c in self.channels:
            payload, b_offset = to_bytes([c.channel_id], 24, payload, b_offset)
            payload, b_offset = to_bytes([len(c.channel_data)], 16, payload, b_offset)
            payload, b_offset = to_bytes(
                c.channel_data, self.bit_width, payload, b_offset
            )

        return payload

    @staticmethod
    def unpack(data: bytes):
        if len(data) < 4:
            raise ValueError(
                f"Invalid broadband data size {len(data)}: expected at least 4 bytes"
            )

        # first bit of the payload is the signed bool
        # remaining 7 bits are the bit width
        bit_width = struct.unpack("<B", data[0:1])[0] >> 1
        signed = (struct.unpack("<B", data[0:1])[0] & 1) == 1
        num_channels = (data[1] << 16) | (data[2] << 8) | data[3]
        sample_rate = struct.unpack("<H", data[4:6])[0]

        payload = data[6:]
        end_bit = 0

        channels = []
        for c in range(num_channels):
            a, end_bit, payload = to_ints(payload, 24, 1, end_bit)

            channel_id = a[0]

            b, end_bit, payload = to_ints(payload, 16, 1, end_bit)
            num_samples = b[0]

            channel_data, end_bit, payload = to_ints(
                payload, bit_width, num_samples, end_bit
            )

            channels.append(
                NDTPPayloadBroadband.ChannelData(
                    channel_id=channel_id,
                    channel_data=channel_data,
                )
            )

        return NDTPPayloadBroadband(signed, bit_width, sample_rate, channels)


@dataclass
class NDTPPayloadSpiketrain:
    BIT_WIDTH = 2
    spike_counts: List[int]

    def pack(self):
        payload = bytearray()
        payload += struct.pack("<L", len(self.spike_counts))
        payload, _ = to_bytes(self.spike_counts, self.BIT_WIDTH, payload)
        return payload

    @staticmethod
    def unpack(data: bytes):
        num_spikes = struct.unpack("<L", data[:4])[0]
        unpacked, _, ___ = to_ints(
            data[4:], NDTPPayloadSpiketrain.BIT_WIDTH, num_spikes
        )
        return NDTPPayloadSpiketrain(unpacked)


@dataclass
class NDTPHeader:
    data_type: int
    timestamp: int
    seq_number: int

    STRUCT = struct.Struct("<BIQH")

    def pack(self):
        return NDTPHeader.STRUCT.pack(
            NDTP_VERSION, self.data_type, self.timestamp, self.seq_number
        )

    @staticmethod
    def unpack(data: bytes):
        if len(data) < NDTPHeader.STRUCT.size:
            raise ValueError(
                f"Invalid header size {len(data)}: expected {NDTPHeader.STRUCT.size} (got {len(data)})"
            )

        version = struct.unpack("<B", data[:1])[0]
        if version != NDTP_VERSION:
            raise ValueError(
                f"Incompatible version {version}: expected {hex(NDTP_VERSION)}, got {hex(version)}"
            )

        _, data_type, timestamp, seq_number = NDTPHeader.STRUCT.unpack(data)
        return NDTPHeader(data_type, timestamp, seq_number)


@dataclass
class NDTPMessage:
    header: NDTPHeader
    payload: any

    @staticmethod
    def crc16(data: bytes, poly: int = 0x8005, init: int = 0xFFFF) -> int:
        crc = init

        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1

        return crc & 0xFFFF

    @staticmethod
    def crc16_verify(data: bytes, crc16: int) -> bool:
        return NDTPMessage.crc16(data) == crc16

    def pack(self):
        header = self.header.pack()
        payload = self.payload.pack() if self.payload else bytes()

        crc16 = struct.pack("<H", NDTPMessage.crc16(header + payload))

        return header + payload + crc16

    @staticmethod
    def unpack(data: bytes):
        header = NDTPHeader.unpack(data[: NDTPHeader.STRUCT.size])
        crc16 = struct.unpack("<H", data[-2:])[0]

        pbytes = data[NDTPHeader.STRUCT.size : -2]
        pdtype = header.data_type

        if pdtype == DataType.kBroadband:
            payload = NDTPPayloadBroadband.unpack(pbytes)
        elif pdtype == DataType.kSpiketrain:
            payload = NDTPPayloadSpiketrain.unpack(pbytes)
        else:
            raise ValueError(f"unknown data type {pdtype}")

        if not NDTPMessage.crc16_verify(data[:-2], crc16):
            raise ValueError(f"CRC16 verification failed (expected {crc16})")

        return NDTPMessage(header, payload)
