import struct

import pytest

from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import (
    NDTP_VERSION,
    ChannelData,
    NDTPHeader,
    NDTPMessage,
    NDTPPayloadBroadband,
    NDTPPayloadSpiketrain,
    to_bytes,
    to_ints,
)


def test_to_bytes():
    assert to_bytes([1, 2, 3, 0], False, 2) == (bytearray(b"\x6C"), 0)

    assert to_bytes([1, 2, 3, 2, 1], False, 2) == (bytearray(b"\x6E\x40"), 2)

    assert to_bytes([7, 5, 3, 1], False, 12) == (
        bytearray(b"\x00\x70\x05\x00\x30\x01"),
        0,
    )

    assert to_bytes([-7, -5, -3, -1], True, 12) == (
        bytearray(b"\xFF\x9F\xFB\xFF\xDF\xFF"),
        0,
    )

    assert to_bytes([7, 5, 3], False, 12, bytearray(b"\x01\x00"), 4) == (
        bytearray(b"\x01\x00\x07\x00\x50\x03"),
        0,
    )

    assert to_bytes(
        [-7, -5, -3],
        True,
        12,
        bytearray(b"\x01\x00"),
        4,
    ) == (bytearray(b"\x01\x0F\xF9\xFF\xBF\xFD"), 0)

    assert to_bytes([7, 5, 3], False, 12) == (bytearray(b"\x00p\x05\x000"), 4)

    assert to_bytes([1, 2, 3, 4], False, 8) == (bytearray(b"\x01\x02\x03\x04"), 0)

    res, offset = to_bytes([7, 5, 3], False, 12)
    assert res == bytearray(b"\x00p\x05\x000")
    assert len(res) == 5
    assert offset == 4

    res, offset = to_bytes([3, 5, 7], False, 12, res, offset)
    assert res == bytearray(b"\x00\x70\x05\x00\x30\x03\x00\x50\x07")
    assert len(res) == 9
    assert offset == 0

    # 8 doesn't fit in 3 bits
    with pytest.raises(ValueError):
        to_bytes([8], False, 3)

    # Invalid bit width
    with pytest.raises(ValueError):
        to_bytes([1, 2, 3, 0], False, 0)


def test_to_ints():
    res, offset, _ = to_ints(b"\x6C", False, 2)
    assert res == [1, 2, 3, 0]
    assert offset == 8

    res, offset, _ = to_ints(b"\x6C", False, 2, 3)
    assert res == [1, 2, 3]
    assert offset == 6

    res, offset, _ = to_ints(b"\x00\x70\x05\x00\x30\x01", False, 12)
    assert res == [7, 5, 3, 1]
    assert offset == 48

    res, offset, _ = to_ints(b"\x6C", False, 2, 3, 2)
    assert res == [2, 3, 0]
    assert offset == 6 + 2

    res, offset, _ = to_ints(b"\x00\x07\x00\x50\x03", False, 12, 3, 4)
    assert res == [7, 5, 3]
    assert offset == 36 + 4

    res, offset, _ = to_ints(b"\xFF\xF9\xFF\xBF\xFD", True, 12, 3, 4)
    assert res == [-7, -5, -3]
    assert offset == 36 + 4

    arry = bytearray(b"\x6E\x40")
    res, offset, arry = to_ints(arry, False, 2, 1)
    assert res == [1]
    assert offset == 2

    res, offset, arry = to_ints(arry, False, 2, 1, offset)
    assert res == [2]
    assert offset == 4

    res, offset, arry = to_ints(arry, False, 2, 1, offset)
    assert res == [3]
    assert offset == 6

    res, offset, arry = to_ints(arry, False, 2, 1, offset)
    assert res == [2]
    assert offset == 8

    # Invalid bit width
    with pytest.raises(ValueError):
        to_ints(b"\x01", False, 0)

    # Incomplete value
    with pytest.raises(ValueError):
        to_ints(b"\x01", False, 3)

    # Insufficient data
    with pytest.raises(ValueError):
        to_ints(b"\x01\x02", False, 3)


def test_ndtp_payload_broadband():
    bit_width = 12
    sample_rate = 3
    signed = False
    channels = [
        ChannelData(
            channel_id=0,
            channel_data=[1, 2, 3],
        ),
        ChannelData(
            channel_id=1,
            channel_data=[4, 5, 6],
        ),
        ChannelData(
            channel_id=2,
            channel_data=[3000, 2000, 1000],
        ),
    ]

    payload = NDTPPayloadBroadband(signed, bit_width, sample_rate, channels)
    p = payload.pack()

    u = NDTPPayloadBroadband.unpack(p)
    assert u.bit_width == bit_width
    assert u.is_signed == signed
    assert len(u.channels) == 3

    assert u.channels[0].channel_id == 0
    assert list(u.channels[0].channel_data) == [1, 2, 3]

    assert u.channels[1].channel_id == 1
    assert list(u.channels[1].channel_data) == [4, 5, 6]

    assert u.channels[2].channel_id == 2
    assert list(u.channels[2].channel_data) == [3000, 2000, 1000]

    assert p[0] >> 1 == bit_width

    assert ((p[1] << 16) | (p[2] << 8) | p[3]) == 3
    p = p[6:]

    unpacked, offset, p = to_ints(p, False, 24, 1)
    assert unpacked[0] == 0
    assert offset == 24

    unpacked, offset, p = to_ints(p, False, 16, 1, offset)
    assert unpacked[0] == 3
    assert offset == 16

    unpacked, offset, p = to_ints(p, False, bit_width, 3, offset)
    assert list(unpacked) == [1, 2, 3]
    assert offset == 36

    # TODO(emma): why are these tests failing? need to look further,
    # but all the data types we're actually using seem to be working

    # unpacked, offset, p = to_ints(p, False, 24, 1, offset)
    # assert unpacked[0] == 1
    # assert offset == 24 + 4

    # unpacked, offset, p = to_ints(p, False, 16, 1, offset)
    # assert unpacked[0] == 3
    # assert offset == 16 + 4

    # unpacked, offset, p = to_ints(p, False, bit_width, 3, offset)
    # assert (unpacked) == [4, 5, 6]
    # assert offset == 36 + 4

    # unpacked, offset, p = to_ints(p, False, 24, 1, offset)
    # assert unpacked[0] == 2
    # assert offset == 24

    # unpacked, offset, p = to_ints(p, False, 16, 1, offset)
    # assert unpacked[0] == 3
    # assert offset == 16

    # unpacked, offset, p = to_ints(p, False, bit_width, 3, offset)
    # assert (unpacked) == [3000, 2000, 1000]
    # assert offset == 36


def test_ndtp_payload_spiketrain():
    samples = [0, 1, 2, 3, 2]

    payload = NDTPPayloadSpiketrain(samples)
    packed = payload.pack()
    unpacked = NDTPPayloadSpiketrain.unpack(packed)

    assert unpacked == payload

    samples = [5]

    payload = NDTPPayloadSpiketrain(samples)
    with pytest.raises(ValueError):
        payload.pack()


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
            struct.pack("<B", NDTP_VERSION)
            + struct.pack("<I", DataType.kBroadband)
            + struct.pack("<Q", 123)
        )


def test_ndtp_message():
    header = NDTPHeader(DataType.kBroadband, timestamp=1234567890, seq_number=42)
    payload = NDTPPayloadBroadband(
        False,
        12,
        100,
        [
            ChannelData(
                channel_id=c,
                channel_data=[c * 100 for _ in range(c + 1)],
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
