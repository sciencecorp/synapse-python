from typing import Optional
from synapse.channel_mask import ChannelMask
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.optical_stim_pb2 import OpticalStimConfig


class OpticalStimulation(Node):
    type = NodeType.kOpticalStim

    def __init__(self, channel_mask = ChannelMask()):
        self.channel_mask = channel_mask

    def _to_proto(self):
        n = NodeConfig()
        p = OpticalStimConfig()
        p.peripheral_id = 0
        for i in self.channel_mask.iter_channels():
            p.pixel_mask.append(i)
        p.bit_width = 10
        p.sample_rate = 20000
        p.gain = 1

        n.optical_stim.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[OpticalStimConfig]):
        if proto is None:
            return OpticalStimulation()

        if not isinstance(proto, OpticalStimConfig):
            raise ValueError("proto is not of type OpticalStimConfig")

        return OpticalStimulation()
