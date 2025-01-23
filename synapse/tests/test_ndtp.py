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
    hexstring = " ".join(f"{i:02x}" for i in p)
    assert hexstring == "18 00 00 03 00 00 03 00 00 00 00 03 00 10 02 00 30 00 00 10 00 30 04 00 50 06 00 00 02 00 03 bb 87 d0 3e 80"

    assert p[0] == (bit_width << 1) | (is_signed << 0)
    
    # number of channels
    assert p[1] == 0
    assert p[2] == 0
    assert p[3] == 3

    # sample rate
    assert p[4] == 0
    assert p[5] == 0
    assert p[6] == 3

    # ch 0 channel_id, 0 (24 bits, 3 bytes)
    assert p[7] == 0
    assert p[8] == 0
    assert p[9] == 0

    # ch 0 num_samples, 3 (16 bits, 2 bytes)
    assert p[10] == 0
    assert p[11] == 3

    # ch 0 channel_data, 1, 2, 3 (12 bits, 1.5 bytes each)
    # 0000 0000  0001 0000  0000 0010  0000 0000  0011 ....
    assert p[12] == 0
    assert p[13] == 16
    assert p[14] == 2
    assert p[15] == 0
    assert p[16] >= 3

    # ch 1 channel_id, 1 (24 bits, 3 bytes, starting from 4 bit offset)
    # 0011 0000  0000 0000  0000 0000  0001 ....
    assert p[16] == 48
    assert p[17] == 0
    assert p[18] == 0
    assert p[19] >= 16

    # ch 1 num_samples, 3 (16 bits, 2 bytes, starting from 4 bit offset)
    # 0001 0000  0000 0000  0011 ....
    assert p[19] == 16
    assert p[20] == 0
    assert p[21] >= 48

    # ch 1 channel_data, 4, 5, 6 (12 bits, 1.5 bytes each)
    # 0011 0000  0000 0100  0000 0000  0101 0000  0000 0110
    assert p[21] == 48
    assert p[22] == 4
    assert p[23] == 0
    assert p[24] == 80
    assert p[25] >= 6

    # ch 2 channel_id, 2 (24 bits, 3 bytes)
    # 0000 0000  0000 0000  0000 0010
    assert p[26] == 0
    assert p[27] == 0
    assert p[28] == 2

    # ch 2 num_samples, 3 (16 bits, 2 bytes)
    # 0000 0000  0000 0011
    assert p[29] == 0
    assert p[30] == 3

    # ch 2 channel_data, 3000, 2000, 1000 (12 bits, 1.5 bytes each)
    # 1011 1011  1000 0111  1101 0000  0011 1110  1000 ....
    assert p[31] == 187
    assert p[32] == 135
    assert p[33] == 208
    assert p[34] == 62
    assert p[35] >= 128

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
    p = p[7:]

    unpacked, offset, p = to_ints(p, bit_width=24, count=1)
    assert unpacked[0] == 0
    assert offset == 24

    unpacked, offset, p = to_ints(p, bit_width=16, count=1, start_bit=offset)
    assert unpacked[0] == 3
    assert offset == 16

    unpacked, offset, p = to_ints(p, bit_width=bit_width, count=3, start_bit=offset)
    assert unpacked == [1, 2, 3]
    assert offset == 36

def test_ndtp_payload_broadband_large():
    n_samples = 20000
    bit_width = 16
    sample_rate = 100000
    is_signed = False
    channels = [
        NDTPPayloadBroadbandChannelData(
            channel_id=0,
            channel_data=[i for i in range(n_samples)],
        ),
        NDTPPayloadBroadbandChannelData(
            channel_id=1,
            channel_data=[i + 1 for i in range(n_samples)],
        ),
        NDTPPayloadBroadbandChannelData(
            channel_id=2,
            channel_data=[i + 2 for i in range(n_samples)],
        ),
    ]

    payload = NDTPPayloadBroadband(is_signed, bit_width, sample_rate, channels)
    packed = payload.pack()

    unpacked = NDTPPayloadBroadband.unpack(packed)
    assert unpacked.bit_width == bit_width
    assert unpacked.is_signed == is_signed
    assert len(unpacked.channels) == 3

    assert unpacked.channels[0].channel_id == 0
    assert list(unpacked.channels[0].channel_data) == [i for i in range(n_samples)]

    assert unpacked.channels[1].channel_id == 1
    assert list(unpacked.channels[1].channel_data) == [i + 1 for i in range(n_samples)]

    assert unpacked.channels[2].channel_id == 2
    assert list(unpacked.channels[2].channel_data) == [i + 2 for i in range(n_samples)]
    

def test_ndtp_payload_spiketrain():
    samples = [0, 1, 2, 3, 4, 5, 6]

    payload = NDTPPayloadSpiketrain(10, samples)
    packed = payload.pack()
    hexstring = " ".join(f"{i:02x}" for i in packed)
    print(hexstring)

    assert packed[0] == 0
    assert packed[1] == 0
    assert packed[2] == 0
    assert packed[3] == 7
    assert packed[4] == 10

    # 0000 0001 0010 0011 0100 0101 0110 0000
    assert packed[5] == 1
    assert packed[6] == 35
    assert packed[7] == 69
    assert packed[8] == 96


    unpacked = NDTPPayloadSpiketrain.unpack(packed)

    assert unpacked == payload
    assert unpacked.bin_size_ms == 10
    assert list(unpacked.spike_counts) == samples

    print("2s")
    samples = [2, 2, 2, 2, 2, 2, 2, 2, 2, 2]

    payload = NDTPPayloadSpiketrain(10, samples)
    packed = payload.pack()
    hexstring = " ".join(f"{i:02x}" for i in packed)
    print(hexstring)

    assert packed[3] == 10
    assert packed[4] == 10
    assert packed[5] == 34
    assert packed[6] == 34
    assert packed[7] == 34
    assert packed[8] == 34
    assert packed[8] == 34

    unpacked = NDTPPayloadSpiketrain.unpack(packed)

    assert unpacked == payload
    assert unpacked.bin_size_ms == 10
    assert list(unpacked.spike_counts) == samples


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

def test_ndtp_message_broadband():
    header = NDTPHeader(DataType.kBroadband, timestamp=1234567890, seq_number=42)
    payload = NDTPPayloadBroadband(
        bit_width=12,
        sample_rate=3,
        is_signed=False,
        channels=[
            NDTPPayloadBroadbandChannelData(
                channel_id=c,
                channel_data=[s * 1000 for s in range(c + 1)],
            )
            for c in range(3)
        ],
    )
    message = NDTPMessage(header, payload)

    packed = message.pack()
    assert message._crc16 == 19660

    hexstring = " ".join(f"{i:02x}" for i in packed)
    assert hexstring == "01 02 00 00 00 00 49 96 02 d2 00 2a 18 00 00 03 00 00 03 00 00 00 00 01 00 00 00 00 10 00 20 00 3e 80 00 00 20 00 30 00 3e 87 d0 4c cc"

    unpacked = NDTPMessage.unpack(packed)
    assert message._crc16 == 19660

    assert unpacked.header == message.header
    assert isinstance(unpacked.payload, NDTPPayloadBroadband)
    assert unpacked.payload == message.payload

def test_ndtp_message_broadband_large():
    header = NDTPHeader(DataType.kBroadband, timestamp=1234567890, seq_number=42)
    payload = NDTPPayloadBroadband(
        bit_width=16,
        sample_rate=36000,
        is_signed=False,
        channels=[
            NDTPPayloadBroadbandChannelData(
                channel_id=c,
                channel_data=[i for i in range(10000)],
            )
            for c in range(20)
        ],
    )
    message = NDTPMessage(header, payload)

    packed = message.pack()
    assert message._crc16 == 32263

    unpacked = NDTPMessage.unpack(packed)
    assert unpacked._crc16 == 32263

    assert unpacked.header == message.header
    assert isinstance(unpacked.payload, NDTPPayloadBroadband)
    assert unpacked.payload == message.payload
    
    u_payload = unpacked.payload
    assert u_payload.bit_width == payload.bit_width
    assert u_payload.sample_rate == payload.sample_rate
    assert u_payload.is_signed == payload.is_signed
    assert len(u_payload.channels) == len(payload.channels)
    for i, c in enumerate(payload.channels):
        assert u_payload.channels[i].channel_id == c.channel_id
        assert list(u_payload.channels[i].channel_data) == list(c.channel_data)

def test_ndtp_message_spiketrain():
    header = NDTPHeader(DataType.kSpiketrain, timestamp=1234567890, seq_number=42)
    payload = NDTPPayloadSpiketrain(bin_size_ms=10, spike_counts=[1, 2, 3, 2, 1])
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
