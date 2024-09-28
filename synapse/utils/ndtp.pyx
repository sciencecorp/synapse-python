# ndtp.pyx
import cython
import struct
from typing import List, Tuple

from cython cimport boundscheck, wraparound
from cpython.buffer cimport PyBUF_SIMPLE
from cpython.bytes cimport PyBytes_FromStringAndSize
from cython.view cimport array as cvarray
from libc.stdint cimport uint8_t, uint16_t, uint64_t, int64_t

from synapse.api.datatype_pb2 import DataType


cdef int DATA_TYPE_K_BROADBAND = DataType.kBroadband
cdef int DATA_TYPE_K_SPIKETRAIN = DataType.kSpiketrain

cdef object NDTPHeader_STRUCT = struct.Struct("<BIQH")

NDTP_VERSION = 0x01
cdef int NDTPPayloadSpiketrain_BIT_WIDTH = 2


@boundscheck(False)
@wraparound(False)
def to_bytes(
    values,
    bint is_signed,
    int bit_width,
    existing: bytearray = None,
    int writing_bit_offset = 0,
    byteorder: str = 'big'
) -> Tuple[bytearray, int]:
    cdef int num_values = len(values)
    cdef int num_bits_to_write = num_values * bit_width

    # Initialize buffer
    cdef bytearray buffer
    cdef int buffer_length
    cdef int bit_offset
    if existing is None:
        buffer = bytearray()
        buffer_length = 0
        bit_offset = 0
    else:
        buffer = existing
        buffer_length = len(buffer)
        bit_offset = (buffer_length - 1) * 8 + writing_bit_offset if buffer_length > 0 else 0

    cdef int total_bits_needed = bit_offset + num_bits_to_write
    cdef int total_bytes_needed = (total_bits_needed + 7) // 8

    # Extend buffer if necessary
    if len(buffer) < total_bytes_needed:
        buffer.extend([0] * (total_bytes_needed - len(buffer)))

    # Get a writable memoryview of the buffer
    cdef unsigned char[::1] buffer_view = buffer

    cdef int64_t min_value, max_value
    if is_signed:
        min_value = -(1 << (bit_width - 1))
        max_value = (1 << (bit_width - 1)) - 1
    else:
        min_value = 0
        max_value = (1 << bit_width) - 1

    cdef int64_t value
    cdef uint64_t value_unsigned
    cdef int bits_remaining, byte_index, bit_index, bits_in_current_byte, shift
    cdef unsigned char bits_to_write
    cdef bint byteorder_is_little

    if byteorder == 'little':
        byteorder_is_little = True
    elif byteorder == 'big':
        byteorder_is_little = False
    else:
        raise ValueError(f"Invalid byteorder: {byteorder}")

    for py_value in values:
        value = py_value
        if not (min_value <= value <= max_value):
            raise ValueError(f"Value {value} cannot be represented in {bit_width} bits")

        # Handle negative values for signed integers
        if is_signed and value < 0:
            value_unsigned = (1 << bit_width) + value  # Two's complement
        else:
            value_unsigned = value

        bits_remaining = bit_width
        while bits_remaining > 0:
            byte_index = bit_offset // 8
            bit_index = bit_offset % 8

            bits_in_current_byte = min(8 - bit_index, bits_remaining)
            shift = bits_remaining - bits_in_current_byte

            # Extract the bits to write
            bits_to_write = (value_unsigned >> shift) & ((1 << bits_in_current_byte) - 1)

            if byteorder_is_little:
                # Align bits to the correct position in the byte
                bits_to_write <<= bit_index
            else:
                bits_to_write <<= (8 - bit_index - bits_in_current_byte)

            # Write bits into the buffer
            buffer_view[byte_index] |= bits_to_write

            bits_remaining -= bits_in_current_byte
            bit_offset += bits_in_current_byte

    final_bit_offset = bit_offset % 8
    if final_bit_offset == 0 and total_bytes_needed < len(buffer):
        # Trim the extra byte if we've not used any bits in it
        buffer = buffer[:total_bytes_needed]

    return buffer, final_bit_offset


@boundscheck(False)
@wraparound(False)
def to_ints(
    data,
    bint is_signed,
    int bit_width,
    int count = 0,
    int start_bit = 0,
    byteorder: str = 'big'
) -> Tuple[List[int], int, object]:
    if bit_width <= 0:
        raise ValueError("bit width must be > 0")

    cdef int truncate_bytes = start_bit // 8
    start_bit = start_bit % 8

    data = data[truncate_bytes:]

    # Convert data to a memoryview
    cdef const unsigned char[::1] data_view

    if isinstance(data, (bytes, bytearray)):
        data_view = data
    else:
        raise TypeError(f"Unsupported data type: {type(data)}")

    cdef Py_ssize_t data_len = len(data_view)

    if count > 0 and data_len < (bit_width * count + 7) // 8:
        raise ValueError(
            f"insufficient data for {count} x {bit_width} bit values "
            f"(expected {(bit_width * count + 7) // 8} bytes, given {data_len} bytes)"
        )

    cdef int current_value = 0
    cdef int bits_in_current_value = 0
    cdef int mask = (1 << bit_width) - 1
    cdef int total_bits_read = 0
    cdef int byte_index, bit_index, bit
    cdef int start
    cdef int value_index = 0
    cdef int max_values = count if count > 0 else (data_len * 8) // bit_width
    cdef int[::1] values_array = cython.view.array(shape=(max_values,), itemsize=cython.sizeof(cython.int), format="i")
    cdef int bit_width_minus1 = bit_width - 1
    cdef int sign_bit = 1 << bit_width_minus1
    cdef uint8_t byte  # Declare byte here, outside the loop

    for byte_index in range(data_len):
        byte = data_view[byte_index]  # Initialize byte inside the loop

        if byteorder == 'little':
            start = start_bit if byte_index == 0 else 0
            for bit_index in range(start, 8):
                bit = (byte >> bit_index) & 1
                current_value |= bit << bits_in_current_value
                bits_in_current_value += 1
                total_bits_read += 1

                if bits_in_current_value == bit_width:
                    if is_signed:
                        if current_value & sign_bit:
                            current_value = current_value - (1 << bit_width)
                    else:
                        current_value = current_value & mask
                    values_array[value_index] = current_value
                    value_index += 1
                    current_value = 0
                    bits_in_current_value = 0

                    if count > 0 and value_index == count:
                        end_bit = start_bit + total_bits_read
                        return [values_array[i] for i in range(value_index)], end_bit, data

        elif byteorder == 'big':
            start = start_bit if byte_index == 0 else 0
            for bit_index in range(7 - start, -1, -1):
                bit = (byte >> bit_index) & 1
                current_value = (current_value << 1) | bit
                bits_in_current_value += 1
                total_bits_read += 1

                if bits_in_current_value == bit_width:
                    if is_signed:
                        if current_value & sign_bit:
                            current_value = current_value - (1 << bit_width)
                    else:
                        current_value = current_value & mask
                    values_array[value_index] = current_value
                    value_index += 1
                    current_value = 0
                    bits_in_current_value = 0

                    if count > 0 and value_index == count:
                        end_bit = start_bit + total_bits_read
                        return [values_array[i] for i in range(value_index)], end_bit, data

        else:
            raise ValueError(f"Invalid byteorder: {byteorder}")

    if bits_in_current_value > 0:
        if bits_in_current_value == bit_width:
            if is_signed and (current_value & sign_bit):
                current_value = current_value - (1 << bit_width)
            else:
                current_value = current_value & mask
            values_array[value_index] = current_value
            value_index += 1
        elif count == 0:
            raise ValueError(
                f"{bits_in_current_value} bits left over, not enough to form a complete value of bit width {bit_width}"
            )

    if count > 0:
        value_index = min(value_index, count)

    end_bit = start_bit + total_bits_read
    return [values_array[i] for i in range(value_index)], end_bit, data


cdef class ChannelData:
    cdef public int channel_id 
    cdef public int[::1] channel_data 

    def __init__(self, int channel_id, channel_data):
        cdef int size  # Declare variables here
        cdef int i

        self.channel_id = channel_id
        # Convert channel_data to memoryview if it's not already
        if isinstance(channel_data, list):
            size = len(channel_data)
            self.channel_data = cython.view.array(
                shape=(size,), itemsize=cython.sizeof(cython.int), format="i"
            )
            for i in range(size):
                self.channel_data[i] = channel_data[i]
        else:
            self.channel_data = channel_data

    def __eq__(self, other):
        if not isinstance(other, ChannelData):
            return False
        return (
            self.channel_id == other.channel_id and
            list(self.channel_data) == list(other.channel_data)
        )

    def __ne__(self, other):
        return not self.__eq__(other)


cdef class NDTPPayloadBroadband:
    cdef public bint is_signed
    cdef public int bit_width
    cdef public int sample_rate
    cdef public list channels  # List of ChannelData objects

    def __init__(self, bint is_signed, int bit_width, int sample_rate, channels):
        self.is_signed = is_signed
        self.bit_width = bit_width
        self.sample_rate = sample_rate
        self.channels = channels

    def pack(self):
        cdef int n_channels = len(self.channels)
        cdef bytearray payload = bytearray()

        # First byte: bit width and signed flag
        payload += struct.pack(
            ">B", ((self.bit_width & 0x7F) << 1) | (1 if self.is_signed else 0)
        )

        # Next three bytes: number of channels (24-bit integer)
        payload += n_channels.to_bytes(3, byteorder='big', signed=False)

        # Next two bytes: sample rate (16-bit integer)
        payload += struct.pack(">H", self.sample_rate)

        cdef ChannelData c
        for c in self.channels:
            # Pack channel_id (3 bytes, 24 bits)
            payload += c.channel_id.to_bytes(3, byteorder='big', signed=False)

            # Pack number of samples (2 bytes, 16 bits)
            payload += struct.pack(">H", len(c.channel_data))

            # Pack channel_data
            channel_data_bytes, _ = to_bytes(
                c.channel_data, self.is_signed, self.bit_width
            )
            payload += channel_data_bytes

        return payload

    @staticmethod
    def unpack(data):
        if isinstance(data, bytes):
            data = bytearray(data)

        cdef int len_data = len(data)
        if len_data < 6:
            raise ValueError(
                f"Invalid broadband data size {len_data}: expected at least 6 bytes"
            )

        cdef int bit_width = data[0] >> 1
        cdef bint is_signed = (data[0] & 1) == 1
        cdef int num_channels = int.from_bytes(data[1:4], 'big')
        cdef int sample_rate = struct.unpack(">H", data[4:6])[0]

        cdef int pos = 6  # Starting byte position after the header

        cdef list channels = []
        cdef int channel_id, num_samples
        cdef list channel_data
        cdef ChannelData channel

        for _ in range(num_channels):
            # Unpack channel_id (3 bytes, big-endian)
            if pos + 3 > len(data):
                raise ValueError("Incomplete data for channel_id")
            channel_id = int.from_bytes(data[pos:pos+3], 'big')
            pos += 3

            # Unpack num_samples (2 bytes, big-endian)
            if pos + 2 > len(data):
                raise ValueError("Incomplete data for num_samples")
            num_samples = struct.unpack(">H", data[pos:pos+2])[0]
            pos += 2

            # Calculate the number of bits and bytes needed for channel data
            total_bits = num_samples * bit_width
            bytes_needed = (total_bits + 7) // 8  # Round up to the nearest byte

            # Ensure we have enough data
            if pos + bytes_needed > len(data):
                raise ValueError("Incomplete data for channel_data")
            channel_data_bytes = data[pos:pos + bytes_needed]
            pos += bytes_needed

            # Unpack channel_data
            channel_data, _, _ = to_ints(
                channel_data_bytes, is_signed, bit_width, num_samples
            )

            channel = ChannelData(channel_id, channel_data)
            channels.append(channel)

        return NDTPPayloadBroadband(is_signed, bit_width, sample_rate, channels)

    def __eq__(self, other):
        if not isinstance(other, NDTPPayloadBroadband):
            return False
        return (
            self.is_signed == other.is_signed and
            self.bit_width == other.bit_width and
            self.sample_rate == other.sample_rate and
            self.channels == other.channels
        )

    def __ne__(self, other):
        return not self.__eq__(other)


cdef class NDTPPayloadSpiketrain:
    cdef public int[::1] spike_counts  # Memoryview of integers

    def __init__(self, spike_counts):
        cdef int size, i
        self.spike_counts = None

        if isinstance(spike_counts, list):
            size = len(spike_counts)
            self.spike_counts = cython.view.array(
                shape=(size,),
                itemsize=cython.sizeof(cython.int),
                format="i",
            )
            for i in range(size):
                self.spike_counts[i] = spike_counts[i]
        else:
            # Assume it's already a memoryview or array
            self.spike_counts = spike_counts

    def pack(self):
        cdef bytearray payload = bytearray()
        cdef int spike_counts_len = len(self.spike_counts)

        # Pack the number of spikes (4 bytes)
        payload += struct.pack("<I", spike_counts_len)  # Use "<I" for unsigned int

        # Pack spike counts
        spike_counts_bytes, _ = to_bytes(
            self.spike_counts, False, NDTPPayloadSpiketrain_BIT_WIDTH
        )
        payload += spike_counts_bytes
        return payload

    @staticmethod
    def unpack(data):
        if isinstance(data, bytes):
            data = bytearray(data)

        cdef int len_data = len(data)
        if len_data < 4:
            raise ValueError(
                f"Invalid spiketrain data size {len_data}: expected at least 4 bytes"
            )

        cdef int num_spikes = struct.unpack("<I", data[:4])[0]
        cdef bytearray payload = data[4:]
        cdef int bits_needed = num_spikes * NDTPPayloadSpiketrain_BIT_WIDTH
        cdef int bytes_needed = (bits_needed + 7) // 8

        if len(payload) < bytes_needed:
            raise ValueError("Insufficient data for spike_counts")

        # Unpack spike_counts
        spike_counts, _, _ = to_ints(
            payload[:bytes_needed], False, NDTPPayloadSpiketrain_BIT_WIDTH, num_spikes
        )

        return NDTPPayloadSpiketrain(spike_counts)

    def __eq__(self, other):
        if not isinstance(other, NDTPPayloadSpiketrain):
            return False
        return list(self.spike_counts) == list(other.spike_counts)

    def __ne__(self, other):
        return not self.__eq__(other)


cdef class NDTPHeader:
    cdef public int data_type
    cdef public long long timestamp
    cdef public int seq_number

    STRUCT = struct.Struct("<BIQH")  # Define as a Python class attribute

    def __init__(self, int data_type, long long timestamp, int seq_number):
        self.data_type = data_type
        self.timestamp = timestamp
        self.seq_number = seq_number

    def __eq__(self, other):
        if not isinstance(other, NDTPHeader):
            return False
        return (
            self.data_type == other.data_type and
            self.timestamp == other.timestamp and
            self.seq_number == other.seq_number
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def pack(self):
        cdef bytes packed_data = self.STRUCT.pack(
            NDTP_VERSION, self.data_type, self.timestamp, self.seq_number
        )
        return bytearray(packed_data)

    @staticmethod
    def unpack(data):
        if isinstance(data, bytes):
            data = bytearray(data)

        cdef int expected_size = NDTPHeader.STRUCT.size
        if len(data) < expected_size:
            raise ValueError(
                f"Invalid header size {len(data)}: expected {expected_size}"
            )

        version, data_type, timestamp, seq_number = NDTPHeader.STRUCT.unpack(bytes(data[:expected_size]))
        if version != NDTP_VERSION:
            raise ValueError(
                f"Incompatible version {version}: expected {hex(NDTP_VERSION)}, got {hex(version)}"
            )

        return NDTPHeader(data_type, timestamp, seq_number)


cdef class NDTPMessage:
    cdef public NDTPHeader header
    cdef public object payload

    def __init__(self, NDTPHeader header, payload=None):
        self.header = header
        self.payload = payload

    @staticmethod
    def crc16(bytearray data, int poly=0x8005, int init=0xFFFF) -> int:
        cdef int crc = init
        cdef int byte
        cdef int i

        for byte in data:
            crc ^= byte << 8
            for i in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFFFF  # Ensure crc stays within 16 bits

        return crc & 0xFFFF

    @staticmethod
    def crc16_verify(bytearray data, int crc16):
        cdef bint result = NDTPMessage.crc16(data) == crc16
        return result

    def pack(self):
        cdef bytearray message = bytearray()
        cdef bytearray header_bytes = self.header.pack()
        cdef bytearray payload_bytes = self.payload.pack() if self.payload else bytearray()
        cdef int crc
        cdef bytes crc_bytes

        message += header_bytes
        message += payload_bytes

        crc = NDTPMessage.crc16(message)
        crc_bytes = struct.pack("<H", crc)

        message += crc_bytes  # Appending bytes to bytearray is acceptable

        return message

    @staticmethod
    def unpack(data):
        if isinstance(data, bytes):
            data = bytearray(data)

        cdef int header_size = NDTPHeader_STRUCT.size
        cdef NDTPHeader header
        cdef int crc16_value
        cdef object pbytes
        cdef int pdtype
        cdef object payload = None

        header = NDTPHeader.unpack(data[:header_size])
        crc16_value = struct.unpack("<H", bytes(data[-2:]))[0]

        pbytes = data[header_size:-2]
        pdtype = header.data_type

        if pdtype == DataType.kBroadband:
            payload = NDTPPayloadBroadband.unpack(pbytes)
        elif pdtype == DataType.kSpiketrain:
            payload = NDTPPayloadSpiketrain.unpack(pbytes)
        else:
            raise ValueError(f"unknown data type {pdtype}")

        if not NDTPMessage.crc16_verify(data[:-2], crc16_value):
            raise ValueError(f"CRC16 verification failed (expected {crc16_value})")

        return NDTPMessage(header, payload)