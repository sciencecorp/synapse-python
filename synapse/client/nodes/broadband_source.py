from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.broadband_source_pb2 import BroadbandSourceConfig
from synapse.api.nodes.signal_config_pb2 import SignalConfig
from synapse.client.node import Node


class BroadbandSource(Node):
    type = NodeType.kBroadbandSource

    def __init__(
        self,
        peripheral_id: int,
        bit_width: int,
        sample_rate_hz: int,
        gain: float,
        signal: SignalConfig
    ):
        self.peripheral_id: int = peripheral_id
        self.bit_width: int = bit_width
        self.sample_rate_hz: int = sample_rate_hz
        self.gain: float = gain 
        self.signal: SignalConfig = signal

    def _to_proto(self):
        n = NodeConfig()
        p = BroadbandSourceConfig(
            peripheral_id=self.peripheral_id,
            bit_width=self.bit_width,
            sample_rate_hz=self.sample_rate_hz,
            gain=self.gain,
            signal=self.signal
        )
        n.broadband_source.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[BroadbandSourceConfig]):
        if not proto:
            return BroadbandSource(0, 0, 0, 0, SignalConfig())
        if not isinstance(proto, BroadbandSourceConfig):
            return BroadbandSource(0, 0, 0, 0, SignalConfig())
    
        return BroadbandSource(
            peripheral_id=proto.peripheral_id,
            bit_width=proto.bit_width,
            sample_rate_hz=proto.sample_rate_hz,
            gain=proto.gain,
            signal=proto.signal
        )
