import numpy as np
import pytest

from synapse.server.nodes.stream_out import StreamOut
from synapse.utils.ndtp import NDTPMessage
from synapse.utils.ndtp_types import (
    MAX_CH_PAYLOAD_SIZE_BYTES,
    chunk_channel_data,
    ElectricalBroadbandData,
    SpiketrainData,
)


def test_packing_broadband_data():
    node = StreamOut(id=1)

    assert node.__sequence_number == 0

    # Signed
    sample_data = [
        (1, np.array([-1000, 2000, 1000], dtype=np.int16)),
        (2, np.array([1234, -1234, 1234, 1234], dtype=np.int16)),
        (3, np.array([2000, -2000, 1000, 2000, -2000], dtype=np.int16)),
    ]
    bdata = ElectricalBroadbandData(
        bit_width=16,
        sample_rate=3,
        t0=1234567890,
        samples=sample_data,
        is_signed=True
    )

    packed = node._pack(bdata)

    assert node.__sequence_number == 1

    for i, p in enumerate(packed):
        unpacked = NDTPMessage.unpack(p)

        assert unpacked.header.timestamp == bdata.t0
        assert unpacked.header.seq_number == i

        assert unpacked.payload.bit_width == 16
        assert unpacked.payload.channels[0].channel_id == bdata.samples[i][0]
        assert list(unpacked.payload.channels[0].channel_data) == list(
            bdata.samples[i][1]
        )

    # Unsigned
    sample_data = [
        (1, np.array([1000, 2000, 3000], dtype=np.uint16)),
        (2, np.array([1234, 1234, 1234, 1234], dtype=np.uint16)),
        (3, np.array([1000, 2000, 3000, 4000, 3000], dtype=np.uint16)),
    ]
    bdata = ElectricalBroadbandData(
        bit_width=12,
        sample_rate=3,
        t0=1234567890,
        samples=sample_data,
        is_signed=False
    )

    packed = node._pack(bdata)

    assert node.__sequence_number == 2

    for i, p in enumerate(packed):
        unpacked = NDTPMessage.unpack(p)


def test_packing_broadband_data():
    node = StreamOut(id=1)
    assert node._StreamOut__sequence_number == 0

    n_samples = 10000
    bit_width = 16

    sample_data = [
        (1, np.array([i for i in range(n_samples)], dtype=np.int16)),
    ]
    bdata = ElectricalBroadbandData(
        bit_width=bit_width,
        sample_rate=36000,
        t0=1234567890,
        samples=sample_data,
        is_signed=True
    )

    packed = node._pack(bdata)
    seq = 0
    n_samples = 0
    ch_data = sample_data[0]
    chunks = chunk_channel_data(bit_width, ch_data[1], MAX_CH_PAYLOAD_SIZE_BYTES)

    for chunk in chunks:
        t_chunk = bdata.t0 + round(n_samples * 1e6 / bdata.sample_rate)

        p = packed[seq]
        unpacked = NDTPMessage.unpack(p)
        assert unpacked.header.timestamp == t_chunk
        assert unpacked.header.seq_number == seq

        assert unpacked.payload.bit_width == bit_width
        assert unpacked.payload.sample_rate == bdata.sample_rate
        assert unpacked.payload.is_signed == bdata.is_signed
        assert unpacked.payload.channels[0].channel_id == ch_data[0]
        assert list(unpacked.payload.channels[0].channel_data) == list(chunk)

        n_samples += len(chunk)
        if chunk is list(chunks)[-1]:  # If this is the last chunk for this channel
            n_samples = j
        seq += 1

    sample_data = [
        (1, np.array([i for i in range(n_samples)], dtype=np.uint16)),
    ]
    bdata = ElectricalBroadbandData(
        bit_width=bit_width,
        sample_rate=36000,
        t0=1234567890,
        samples=sample_data,
    )

    node = StreamOut(id=1)
    assert node._StreamOut__sequence_number == 0

    packed = node._pack(bdata)
    seq = 0
    ch_data = sample_data[0]
    chunks = chunk_channel_data(bit_width, ch_data[1], MAX_CH_PAYLOAD_SIZE_BYTES)

    for chunk in chunks:
        p = packed[seq]
        unpacked = NDTPMessage.unpack(p)

        assert unpacked.header.timestamp == bdata.t0
        assert unpacked.header.seq_number == seq

        assert unpacked.payload.bit_width == 16
        assert unpacked.payload.sample_rate == bdata.sample_rate
        assert unpacked.payload.is_signed == bdata.is_signed
        assert unpacked.payload.channels[0].channel_id == ch_data[0]
        assert list(unpacked.payload.channels[0].channel_data) == list(chunk)

        seq += 1


def test_packing_spiketrain_data():
    node = StreamOut(id=1)

    sdata = SpiketrainData(
        t0=1234567890,
        bin_size_ms=10,
        spike_counts=[0, 1, 2, 3, 4, 5, 6],
    )

    packed = node._pack(sdata)[0]
    unpacked = NDTPMessage.unpack(packed)

    assert unpacked.header.timestamp == sdata.t0
    assert unpacked.payload.bin_size_ms == sdata.bin_size_ms
    assert len(unpacked.payload.spike_counts) == len(sdata.spike_counts)

    assert list(unpacked.payload.spike_counts) == list(sdata.spike_counts)
