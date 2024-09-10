from dataclasses import dataclass
from struct import Struct

NDTPHeaderStruct = Struct("<cQBHH")


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
