import asyncio
import pytest
from synapse.api.nodes.broadband_source_pb2 import BroadbandSourceConfig
from synapse.simulator.nodes.broadband_source import BroadbandSource
from synapse.api.nodes.signal_config_pb2 import SignalConfig, ElectrodeConfig
from synapse.api.channel_pb2 import Channel
from synapse.utils.ndtp_types import ElectricalBroadbandData

@pytest.mark.asyncio
async def test_broadband_source_data_generation():
    node = BroadbandSource(id=1)
    
    config = BroadbandSourceConfig(
        peripheral_id=1,
        bit_width=12,
        sample_rate_hz=30000,
        gain=20.0,
        signal=SignalConfig(
            electrode=ElectrodeConfig(
                channels=[
                    Channel(id=1, electrode_id=2, reference_id=3),
                    Channel(id=2, electrode_id=3, reference_id=4)
                ],
                low_cutoff_hz=500.0,
                high_cutoff_hz=6000.0
            )
        )
    )
    
    status = node.configure(config)
    assert status.ok()

    data_received = []

    async def collect_data(_, data):
        data_received.append(data)

    node.add_downstream_node(type('', (), {'on_data_received': collect_data})())
    
    status = node.start()
    assert status.ok()
    
    await asyncio.sleep(1)
    
    status = node.stop() 
    assert status.ok()

    assert len(data_received) > 0
    
    first_packet = data_received[0]
    assert isinstance(first_packet, ElectricalBroadbandData)
    assert first_packet.bit_width == 12
    assert first_packet.sample_rate == 30000
    assert not first_packet.is_signed
    assert len(first_packet.samples) == 2
    
    for channel_id, samples in first_packet.samples:
        assert channel_id in [1, 2]
        for sample in samples:
            assert 0 <= sample < 2**12

def test_broadband_source_invalid_config():
    node = BroadbandSource(id=1)
    
    config = BroadbandSourceConfig(
        peripheral_id=1,
        bit_width=12,
        sample_rate_hz=30000,
        gain=20.0
    )
    
    status = node.configure(config)
    assert status.ok()
    assert not node.running

    config = BroadbandSourceConfig(
        peripheral_id=1,
        bit_width=12,
        sample_rate_hz=30000,
        gain=20.0,
        signal=SignalConfig(
            electrode=ElectrodeConfig(
                low_cutoff_hz=500.0,
                high_cutoff_hz=6000.0
            )
        )
    )
    
    status = node.configure(config)
    assert status.ok()
    assert not node.running

