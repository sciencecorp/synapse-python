from typing import Optional
from synapse.node import Node
from synapse.channel import Channel
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig


class ElectricalBroadband(Node):
    type = NodeType.kElectricalBroadband

    def __init__(
        self, peripheral_id, channels, sample_rate=None, gain=None, bit_width=None
    ):
        self.peripheral_id = peripheral_id
        self.channels = channels
        self.sample_rate = sample_rate
        self.gain = gain
        self.bit_width = bit_width

    def _to_proto(self):
        n = NodeConfig()
        p = ElectricalBroadbandConfig(
            peripheral_id=self.peripheral_id,
            bit_width=self.bit_width,
            sample_rate=self.sample_rate,
            gain=self.gain,
            channels=[c.to_proto() for c in self.channels],
        )
        n.electrical_broadband.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[ElectricalBroadbandConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, ElectricalBroadbandConfig):
            raise ValueError("proto is not of type ElectricalBroadbandConfig")

        channels = [Channel.from_proto(c) for c in proto.channels]
        return ElectricalBroadband(
            proto.peripheral_id,
            channels,
            proto.sample_rate,
            proto.gain,
            proto.bit_width,
        )
