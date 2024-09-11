import struct
from dataclasses import dataclass

NDTP_HEADER_SIZE_BYTES = 20

NDTPHeaderStruct = struct.Struct("<cQBHH")


def deserialize_header(data):
    magic, data_type, t0, seq_num, ch_count = struct.unpack(
        "=IiqHh", data[:NDTP_HEADER_SIZE_BYTES]
    )
    if magic != 0xC0FFEE00:
        print(f"Invalid magic number: {hex(magic)}")
        return None

    return data_type, t0, int(seq_num), ch_count


def deserialize_broadband(t0, ch_count, data):
    channel_data = data[NDTP_HEADER_SIZE_BYTES:]
    return_data = [t0]
    for i in range(ch_count):
        channel_id, sample_count = struct.unpack("=ii", channel_data[0:8])
        channel_data = channel_data[8:]
        samples = struct.unpack(f"={sample_count}h", channel_data[: (2 * sample_count)])
        channel_data = channel_data[2 * sample_count :]
        return_data.append((channel_id, samples))
    return return_data


@dataclass
class NDTPHeader:
    version: int
    data_type: int
    timestamp: int
    seq_number: int
    ch_count: int
    dtype_custom: int

    # @staticmethod
    # def unpack(data: bytes):
    #     version_and_data_type, timestamp, seq_number, ch_count, dtype_custom = NDTPHeaderStruct.unpack(data)
    #     return NDTPHeader(
    #         version,
    #     )


@dataclass
class NDTPMessage:
    header: NDTPHeader
    payload: bytes
    crc16: int
