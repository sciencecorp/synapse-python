from synapse.api.nodes.spike_source_pb2 import SpikeSourceConfig
from synapse.api.nodes.signal_config_pb2 import ElectrodeConfig
from synapse.client.channel import Channel
from synapse.client.nodes.spike_source import SpikeSource

def test_spike_source_to_proto():
    channels = [Channel(id=1, electrode_id=2, reference_id=3)]
    electrodes = ElectrodeConfig(channels=channels, low_cutoff_hz=500.0, high_cutoff_hz=6000.0)
    
    source = SpikeSource(
        peripheral_id=1,
        sample_rate_hz=30000,
        spike_window_ms=2.0,
        gain=20.0,
        threshold_uV=50.0,
        electrodes=electrodes
    )
    
    proto = source._to_proto()

    assert proto.spike_source.peripheral_id == 1
    assert proto.spike_source.sample_rate_hz == 30000
    assert proto.spike_source.spike_window_ms == 2.0
    assert proto.spike_source.gain == 20.0
    assert proto.spike_source.threshold_uV == 50.0
    assert proto.spike_source.electrodes.channels[0].id == 1
    assert proto.spike_source.electrodes.channels[0].electrode_id == 2
    assert proto.spike_source.electrodes.channels[0].reference_id == 3
    assert proto.spike_source.electrodes.low_cutoff_hz == 500.0
    assert proto.spike_source.electrodes.high_cutoff_hz == 6000.0

def test_spike_source_from_proto():
    channels = [Channel(id=1, electrode_id=2, reference_id=3)]
    electrodes = ElectrodeConfig(channels=channels, low_cutoff_hz=500.0, high_cutoff_hz=6000.0)
    
    proto = SpikeSourceConfig(
        peripheral_id=1,
        sample_rate_hz=30000,
        spike_window_ms=2.0,
        gain=20.0,
        threshold_uV=50.0,
        electrodes=electrodes
    )
    
    source = SpikeSource._from_proto(proto)
    
    assert source.peripheral_id == 1
    assert source.sample_rate_hz == 30000
    assert source.spike_window_ms == 2.0
    assert source.gain == 20.0
    assert source.threshold_uV == 50.0
    assert source.electrodes.channels[0].id == 1
    assert source.electrodes.channels[0].electrode_id == 2
    assert source.electrodes.channels[0].reference_id == 3
    assert source.electrodes.low_cutoff_hz == 500.0
    assert source.electrodes.high_cutoff_hz == 6000.0

def test_spike_source_from_invalid_proto():
    # Test with None
    source = SpikeSource._from_proto(None)
    assert source.peripheral_id == 0
    assert source.sample_rate_hz == 0
    assert source.spike_window_ms == 0
    assert source.gain == 0
    assert source.threshold_uV == 0
    assert len(source.electrodes.channels) == 0
    assert source.electrodes.low_cutoff_hz == 0
    assert source.electrodes.high_cutoff_hz == 0
    
    # Test with wrong type
    source = SpikeSource._from_proto("invalid")
    assert source.peripheral_id == 0
    assert source.sample_rate_hz == 0
    assert source.spike_window_ms == 0
    assert source.gain == 0
    assert source.threshold_uV == 0
    assert len(source.electrodes.channels) == 0
    assert source.electrodes.low_cutoff_hz == 0
    assert source.electrodes.high_cutoff_hz == 0
