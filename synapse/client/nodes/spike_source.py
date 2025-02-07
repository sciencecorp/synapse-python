from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.spike_source_pb2 import SpikeSourceConfig
from synapse.api.nodes.signal_config_pb2 import ElectrodeConfig
from synapse.client.node import Node

class SpikeSource(Node):
    type = NodeType.kSpikeSource

    def __init__(
        self,
        peripheral_id: int,
        sample_rate_hz: int,
        spike_window_ms: float,
        gain: float,
        threshold_uV: float,
        electrodes: ElectrodeConfig
    ):
        self.peripheral_id: int = peripheral_id
        self.sample_rate_hz: int = sample_rate_hz
        self.spike_window_ms: float = spike_window_ms
        self.gain: float = gain
        self.threshold_uV: float = threshold_uV
        self.electrodes: ElectrodeConfig = electrodes

    def _to_proto(self):
        n = NodeConfig()
        p = SpikeSourceConfig(
            peripheral_id=self.peripheral_id,
            sample_rate_hz=self.sample_rate_hz,
            spike_window_ms=self.spike_window_ms,
            gain=self.gain,
            threshold_uV=self.threshold_uV,
            electrodes=self.electrodes
        )
        n.spike_source.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[SpikeSourceConfig]):
        if not proto:
            return SpikeSource(0, 0, 0, 0, 0, ElectrodeConfig())
        if not isinstance(proto, SpikeSourceConfig):
            return SpikeSource(0, 0, 0, 0, 0, ElectrodeConfig())

        return SpikeSource(
            peripheral_id=proto.peripheral_id,
            sample_rate_hz=proto.sample_rate_hz,
            spike_window_ms=proto.spike_window_ms,
            gain=proto.gain,
            threshold_uV=proto.threshold_uV,
            electrodes=proto.electrodes
        )
