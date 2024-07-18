from typing import Optional
from synapse.channel_mask import ChannelMask
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig


class ElectricalBroadband(Node):
    type = NodeType.kElectricalBroadband

    def __init__(self, channel_mask=ChannelMask()):
        self.channel_mask = channel_mask

    def _to_proto(self):
        n = NodeConfig()
        p = ElectricalBroadbandConfig()
        p.peripheral_id = 0
        for i in self.channel_mask.iter_channels():
            p.ch_mask.append(i)
        p.bit_width = 10
        p.sample_rate = 20000
        p.gain = 1

        n.electrical_broadband.CopyFrom(p)
        return n

    @staticmethod

    def _from_proto(proto: Optional[ElectricalBroadbandConfig]):
        if not proto:
            return ElectricalBroadband()

        if not isinstance(proto, ElectricalBroadbandConfig):
            raise ValueError("proto is not of type ElectricalBroadbandConfig")

        return ElectricalBroadband()
