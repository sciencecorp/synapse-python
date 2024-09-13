import pytest
import struct
from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import (
    to_bytes,
    to_ints,
    NDTPHeader,
    NDTPMessage,
    NDTPPayloadBroadband,
    NDTPPayloadSpiketrain,
    MAGIC_HEADER,
    NDTP_HEADER_SIZE_BYTES
)

def test_to_bytes():
    assert to_bytes([1, 2, 3, 0], 2) == b'\x6C'

    assert to_bytes([7, 5, 3, 1], 12) == b'\x00\x70\x05\x00\x30\x01'

    assert to_bytes([1, 2, 3, 4], 8) == b'\x01\x02\x03\x04'

    # 8 doesn't fit in 3 bits
    with pytest.raises(ValueError):
        to_bytes([8], 3)

    # Invalid bit width
    with pytest.raises(ValueError):
        to_bytes([1, 2, 3, 0], 0)

def test_to_ints():
    assert to_ints(b'\x6C', 2) == [1, 2, 3, 0]
  
    assert to_ints(b'\x6C', 2, 3) == [1, 2, 3]
  
    assert to_ints(b'\x00\x70\x05\x00\x30\x01', 12) == [7, 5, 3, 1]

    # Invalid bit width
    with pytest.raises(ValueError):
        to_ints(b'\x01', 0)
  
    # Incomplete value
    with pytest.raises(ValueError):
        to_ints(b'\x01', 3)

def test_ndtp_payload_broadband():
    channel_id = 1
    sample_count = 3
    bit_width = 12
    samples = [1000, 2000, 3000]

    payload = NDTPPayloadBroadband(channel_id, sample_count, bit_width, samples)
    packed = payload.pack()
    unpacked = NDTPPayloadBroadband.unpack(packed)
    assert unpacked.channel_id == channel_id
    assert unpacked.sample_count == sample_count
    assert unpacked.bit_width == bit_width
    assert unpacked.channel_data == samples

def test_ndtp_payload_spiketrain():
    samples = [0, 1, 2, 3]

    payload = NDTPPayloadSpiketrain(samples)
    packed = payload.pack()
    unpacked = NDTPPayloadSpiketrain.unpack(packed)
    assert unpacked == payload

def test_ndtp_header():
    header = NDTPHeader(DataType.kBroadband, 1234567890, 42)
    packed = header.pack()
    unpacked = NDTPHeader.unpack(packed)
    assert unpacked == header

    # Invalid magic header
    with pytest.raises(ValueError):
        NDTPHeader.unpack(b'\x01\x02\x03\x04' + packed[4:])

    # Data too smol
    with pytest.raises(ValueError):
        NDTPHeader.unpack(
            struct.pack("<I", MAGIC_HEADER) +
            struct.pack("<I", DataType.kBroadband) +
            struct.pack("<I", 123)
        )

def test_ndtp_message():
    header = NDTPHeader(DataType.kBroadband, 1234567890, 42)
    payload = NDTPPayloadBroadband(1, 3, 16, [1000, 2000, 3000])
    message = NDTPMessage(header, payload, 0xdeadbeef)
    
    packed = message.pack()
    unpacked = NDTPMessage.unpack(packed)
    
    assert unpacked.header == message.header
    assert isinstance(unpacked.payload, NDTPPayloadBroadband)
    assert unpacked.payload == message.payload
    assert unpacked.crc32 == message.crc32

    header.data_type = DataType.kBroadband
    payload = NDTPPayloadBroadband(
        channel_id=123,
        sample_count=5,
        bit_width=12,
        channel_data=[1000, 2000, 3000, 4000, 3000]
    )
    message = NDTPMessage(header, payload, 0xdeadbeef)
    
    packed = message.pack()
    unpacked = NDTPMessage.unpack(packed)
    
    assert unpacked.header == message.header
    assert isinstance(unpacked.payload, NDTPPayloadBroadband)
    assert unpacked.crc32 == message.crc32
    assert unpacked.payload.channel_id == message.payload.channel_id
    assert unpacked.payload.sample_count == message.payload.sample_count
    assert unpacked.payload.bit_width == message.payload.bit_width
    assert unpacked.payload.channel_data == message.payload.channel_data

    with pytest.raises(ValueError):
        NDTPMessage.unpack(b'\x00' * (NDTP_HEADER_SIZE_BYTES + 8))  # Invalid data type

if __name__ == "__main__":
    pytest.main()