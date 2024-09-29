import numpy as np
import pytest

from synapse.api.datatype_pb2 import DataType
from synapse.server.nodes.stream_out import StreamOut
from synapse.utils.ndtp import NDTPMessage
from synapse.utils.ndtp_types import (
    ElectricalBroadbandData,
    SpiketrainData,
)


def test_packing_broadband_data():
    node = StreamOut(id=1)

    sample_data = [
        (1, np.array([-1000, 2000, 3000], dtype=np.int16)),
        (2, np.array([1234, -1234, 1234, 1234], dtype=np.int16)),
        (3, np.array([3000, -2000, 1000, 2000, 3000], dtype=np.int16)),
    ]
    bdata = ElectricalBroadbandData(
        sample_rate=3,
        t0=1234567890,
        samples=sample_data,
    )

    packed = node._pack(bdata)

    for i, p in enumerate(packed):
        unpacked = NDTPMessage.unpack(p)

        assert unpacked.header.timestamp == bdata.t0
        assert unpacked.header.seq_number == i

        assert unpacked.payload.channels[0].channel_id == bdata.samples[i][0]
        assert list(unpacked.payload.channels[0].channel_data) == list(
            bdata.samples[i][1]
        )


def test_packing_spiketrain_data():
    node = StreamOut(id=1)

    sdata = SpiketrainData(
        t0=1234567890,
        spike_counts=[0, 1, 2, 3, 2, 1, 0],
    )

    packed = node._pack(sdata)[0]
    unpacked = NDTPMessage.unpack(packed)

    assert unpacked.header.timestamp == sdata.t0
    assert len(unpacked.payload.spike_counts) == len(sdata.spike_counts)

    assert list(unpacked.payload.spike_counts) == list(sdata.spike_counts)
