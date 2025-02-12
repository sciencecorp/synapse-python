from synapse.api.nodes.broadband_source_pb2 import BroadbandSourceConfig
from synapse.api.nodes.signal_config_pb2 import SignalConfig, ElectrodeConfig
from synapse.client.channel import Channel
from synapse.client.nodes.broadband_source import BroadbandSource

def test_broadband_source_to_proto():
    channels = [Channel(id=1, electrode_id=2, reference_id=3)]
    
    electrode = ElectrodeConfig(channels=channels, low_cutoff_hz=500.0, high_cutoff_hz=6000.0)
    signal = SignalConfig(electrode=electrode)
    
    source = BroadbandSource(
        peripheral_id=1,
        bit_width=12,
        sample_rate_hz=30000,
        gain=20.0,
        signal=signal
    )
    
    proto = source._to_proto()
    
    assert proto.broadband_source.peripheral_id == 1
    assert proto.broadband_source.bit_width == 12
    assert proto.broadband_source.sample_rate_hz == 30000
    assert proto.broadband_source.gain == 20.0
    assert proto.broadband_source.signal.electrode.channels[0].id == 1
    assert proto.broadband_source.signal.electrode.channels[0].electrode_id == 2
    assert proto.broadband_source.signal.electrode.channels[0].reference_id == 3
    assert proto.broadband_source.signal.electrode.low_cutoff_hz == 500.0
    assert proto.broadband_source.signal.electrode.high_cutoff_hz == 6000.0

def test_broadband_source_from_proto():
    proto = BroadbandSourceConfig(
        peripheral_id=1,
        bit_width=12,
        sample_rate_hz=30000,
        gain=20.0
    )
    
    source = BroadbandSource._from_proto(proto)
    
    assert source.peripheral_id == 1
    assert source.bit_width == 12
    assert source.sample_rate_hz == 30000
    assert source.gain == 20.0

def test_broadband_source_from_invalid_proto():
    # Test with None
    source = BroadbandSource._from_proto(None)
    assert source.peripheral_id == 0
    assert source.bit_width == 0
    assert source.sample_rate_hz == 0
    assert source.gain == 0
    
    # Test with wrong type
    source = BroadbandSource._from_proto("invalid")
    assert source.peripheral_id == 0
    assert source.bit_width == 0
    assert source.sample_rate_hz == 0
    assert source.gain == 0
