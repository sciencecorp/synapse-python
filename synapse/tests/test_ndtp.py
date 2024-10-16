import struct

import pytest

from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import (
    NDTP_VERSION,
    NDTPHeader,
    NDTPMessage,
    NDTPPayloadBroadband,
    NDTPPayloadBroadbandChannelData,
    NDTPPayloadSpiketrain,
    to_bytes,
    to_ints,
)


def test_to_bytes():
    assert to_bytes([1, 2, 3, 0], bit_width=2) == (bytearray(b"\x6C"), 0)

    assert to_bytes([1, 2, 3, 2, 1], bit_width=2) == (bytearray(b"\x6E\x40"), 2)

    assert to_bytes([7, 5, 3, 1], bit_width=12) == (
        bytearray(b"\x00\x70\x05\x00\x30\x01"),
        0,
    )

    assert to_bytes([-7, -5, -3, -1], bit_width=12, is_signed=True) == (
        bytearray(b"\xFF\x9F\xFB\xFF\xDF\xFF"),
        0,
    )

    assert to_bytes(
        [7, 5, 3], bit_width=12, existing=bytearray(b"\x01\x00"), writing_bit_offset=4
    ) == (bytearray(b"\x01\x00\x07\x00\x50\x03"), 0)

    assert to_bytes(
        [-7, -5, -3],
        bit_width=12,
        existing=bytearray(b"\x01\x00"),
        writing_bit_offset=4,
        is_signed=True,
    ) == (bytearray(b"\x01\x0F\xF9\xFF\xBF\xFD"), 0)

    assert to_bytes([7, 5, 3], bit_width=12) == (bytearray(b"\x00p\x05\x000"), 4)

    assert to_bytes([1, 2, 3, 4], bit_width=8) == (bytearray(b"\x01\x02\x03\x04"), 0)

    res, offset = to_bytes([7, 5, 3], bit_width=12)
    assert res == bytearray(b"\x00p\x05\x000")
    assert len(res) == 5
    assert offset == 4

    res, offset = to_bytes(
        [3, 5, 7], bit_width=12, existing=res, writing_bit_offset=offset
    )
    assert res == bytearray(b"\x00\x70\x05\x00\x30\x03\x00\x50\x07")
    assert len(res) == 9
    assert offset == 0

    # 8 doesn't fit in 3 bits
    with pytest.raises(ValueError):
        to_bytes([8], 3)

    # Invalid bit width
    with pytest.raises(ValueError):
        to_bytes([1, 2, 3, 0], 0)


def test_to_ints():
    res, offset, _ = to_ints(b"\x6C", 2)
    assert res == [1, 2, 3, 0]
    assert offset == 8

    res, offset, _ = to_ints(b"\x6C", 2, 3)
    assert res == [1, 2, 3]
    assert offset == 6

    res, offset, _ = to_ints(b"\x00\x70\x05\x00\x30\x01", 12)
    assert res == [7, 5, 3, 1]
    assert offset == 48

    res, offset, _ = to_ints(b"\x6C", 2, 3, 2)
    assert res == [2, 3, 0]
    assert offset == 6 + 2

    res, offset, _ = to_ints(b"\x00\x07\x00\x50\x03", 12, 3, 4)
    assert res == [7, 5, 3]
    assert offset == 36 + 4

    res, offset, _ = to_ints(b"\xFF\xF9\xFF\xBF\xFD", 12, 3, 4, is_signed=True)
    assert res == [-7, -5, -3]
    assert offset == 36 + 4

    arry = bytearray(b"\x6E\x40")
    res, offset, arry = to_ints(arry, 2, 1)
    assert res == [1]
    assert offset == 2

    res, offset, arry = to_ints(arry, 2, 1, offset)
    assert res == [2]
    assert offset == 4

    res, offset, arry = to_ints(arry, 2, 1, offset)
    assert res == [3]
    assert offset == 6

    res, offset, arry = to_ints(arry, 2, 1, offset)
    assert res == [2]
    assert offset == 8

    # Invalid bit width
    with pytest.raises(ValueError):
        to_ints(b"\x01", 0)

    # Incomplete value
    with pytest.raises(ValueError):
        to_ints(b"\x01", 3)

    # Insufficient data
    with pytest.raises(ValueError):
        to_ints(b"\x01\x02", 3)


def test_ndtp_payload_broadband():
    bit_width = 12
    sample_rate = 3
    is_signed = False
    channels = [
        NDTPPayloadBroadbandChannelData(
            channel_id=0,
            channel_data=[1, 2, 3],
        ),
        NDTPPayloadBroadbandChannelData(
            channel_id=1,
            channel_data=[4, 5, 6],
        ),
        NDTPPayloadBroadbandChannelData(
            channel_id=2,
            channel_data=[3000, 2000, 1000],
        ),
    ]

    payload = NDTPPayloadBroadband(is_signed, bit_width, sample_rate, channels)
    p = payload.pack()

    assert p[0] == (bit_width << 1) | (is_signed << 0)
    
    # number of channels
    assert p[1] == 0
    assert p[2] == 0
    assert p[3] == 3

    # sample rate
    assert p[4] == 0
    assert p[5] == 3

    # ch 0 channel_id, 0 (24 bits, 3 bytes)
    assert p[6] == 0
    assert p[7] == 0
    assert p[8] == 0

    # ch 0 num_samples, 3 (16 bits, 2 bytes)
    assert p[9] == 0
    assert p[10] == 3

    # ch 0 channel_data, 1, 2, 3 (12 bits, 1.5 bytes each)
    # 0000 0000  0001 0000  0000 0010  0000 0000  0011 ....
    assert p[11] == 0
    assert p[12] == 16
    assert p[13] == 2
    assert p[14] == 0
    assert p[15] >= 3

    # ch 1 channel_id, 1 (24 bits, 3 bytes, starting from 4 bit offset)
    # 0011 0000  0000 0000  0000 0000  0001 ....
    assert p[15] == 48
    assert p[16] == 0
    assert p[17] == 0
    assert p[18] >= 16

    # ch 1 num_samples, 3 (16 bits, 2 bytes, starting from 4 bit offset)
    # 0001 0000  0000 0000  0011 ....
    assert p[18] == 16
    assert p[19] == 0
    assert p[20] >= 48

    u = NDTPPayloadBroadband.unpack(p)
    assert u.bit_width == bit_width
    assert u.is_signed == is_signed
    assert len(u.channels) == 3

    assert u.channels[0].channel_id == 0
    assert list(u.channels[0].channel_data) == [1, 2, 3]

    assert u.channels[1].channel_id == 1
    assert list(u.channels[1].channel_data) == [4, 5, 6]

    assert u.channels[2].channel_id == 2
    assert list(u.channels[2].channel_data) == [3000, 2000, 1000]

    assert p[0] >> 1 == bit_width

    assert (p[1] << 16) | (p[2] << 8) | p[3] == 3
    p = p[6:]

    unpacked, offset, p = to_ints(p, bit_width=24, count=1)
    assert unpacked[0] == 0
    assert offset == 24

    unpacked, offset, p = to_ints(p, bit_width=16, count=1, start_bit=offset)
    assert unpacked[0] == 3
    assert offset == 16

    unpacked, offset, p = to_ints(p, bit_width=bit_width, count=3, start_bit=offset)
    assert unpacked == [1, 2, 3]
    assert offset == 36


def test_ndtp_payload_spiketrain():
    samples = [0, 1, 2, 3, 2]

    payload = NDTPPayloadSpiketrain(samples)
    packed = payload.pack()
    unpacked = NDTPPayloadSpiketrain.unpack(packed)

    assert unpacked == payload


def test_ndtp_header():
    header = NDTPHeader(DataType.kBroadband, 1234567890, 42)
    packed = header.pack()
    unpacked = NDTPHeader.unpack(packed)
    assert unpacked == header

    # Invalid version
    with pytest.raises(ValueError):
        NDTPHeader.unpack(b"\x00" + packed[1:])

    # Data too smol
    with pytest.raises(ValueError):
        NDTPHeader.unpack(
            struct.pack(">B", NDTP_VERSION)
            + struct.pack(">B", DataType.kBroadband)
            + struct.pack(">Q", 123)
        )


def test_ndtp_message():
    header = NDTPHeader(DataType.kBroadband, timestamp=1234567890, seq_number=42)
    payload = NDTPPayloadBroadband(
        bit_width=12,
        sample_rate=3,
        is_signed=False,
        channels=[
            NDTPPayloadBroadbandChannelData(
                channel_id=c,
                channel_data=[c * 3 for _ in range(c + 1)],
            )
            for c in range(3)
        ],
    )
    message = NDTPMessage(header, payload)

    packed = message.pack()

    unpacked = NDTPMessage.unpack(packed)

    assert unpacked.header == message.header
    assert isinstance(unpacked.payload, NDTPPayloadBroadband)
    assert unpacked.payload == message.payload

    header = NDTPHeader(DataType.kSpiketrain, timestamp=1234567890, seq_number=42)
    payload = NDTPPayloadSpiketrain(spike_counts=[1, 2, 3, 2, 1])
    message = NDTPMessage(header, payload)

    packed = message.pack()
    unpacked = NDTPMessage.unpack(packed)

    assert unpacked.header == message.header
    assert isinstance(unpacked.payload, NDTPPayloadSpiketrain)
    assert unpacked.payload == message.payload

    with pytest.raises(ValueError):
        NDTPMessage.unpack(b"\x00" * (NDTPHeader.STRUCT.size + 8))  # Invalid data type


if __name__ == "__main__":
    pytest.main()
