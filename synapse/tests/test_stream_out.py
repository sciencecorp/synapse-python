import pytest
from synapse.api.datatype_pb2 import DataType
from synapse.server.nodes.stream_out import StreamOut
from synapse.utils.ndtp import NDTPMessage
from synapse.utils.types import ElectricalBroadbandData, SpiketrainData


def test_packing_broadband_data():
    node = StreamOut(id=1)

    bdata = ElectricalBroadbandData(
      bit_width = 12,
      t0 = 1234567890,
      channels = [
          ElectricalBroadbandData.ChannelData(
              channel_id=0,
              channel_data=[1000, 2000, 3000],
          ),
          ElectricalBroadbandData.ChannelData(
              channel_id=1,
              channel_data=[1234, 1234, 1234, 1234],
          ),
          ElectricalBroadbandData.ChannelData(
              channel_id=2,
              channel_data=[3000, 2000, 1000, 2000, 3000],
          )
      ]
    )

    packed = node._pack(DataType.kBroadband, bdata)[0]
    unpacked = NDTPMessage.unpack(packed)

    assert unpacked.header.timestamp == bdata.t0
    assert unpacked.payload.bit_width == bdata.bit_width
    assert len(unpacked.payload.channels) == len(bdata.channels)

    for i in range(len(bdata.channels)):
        assert unpacked.payload.channels[i].channel_id == bdata.channels[i].channel_id
        assert unpacked.payload.channels[i].channel_data == bdata.channels[i].channel_data
  

def test_packing_spiketrain_data():
    node = StreamOut(id=1)

    sdata = SpiketrainData(
      t0 = 1234567890,
      spike_counts = [0, 1, 2, 3, 2, 1, 0],
    )

    packed = node._pack(DataType.kSpiketrain, sdata)[0]
    unpacked = NDTPMessage.unpack(packed)

    assert unpacked.header.timestamp == sdata.t0
    assert len(unpacked.payload.spike_counts) == len(sdata.spike_counts)

    assert unpacked.payload.spike_counts == sdata.spike_counts
  