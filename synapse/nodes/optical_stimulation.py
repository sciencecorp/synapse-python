from typing import Optional
from synapse.channel_mask import ChannelMask
from synapse.node import Node
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.optical_stim_pb2 import OpticalStimConfig


class OpticalStimulation(Node):
    type = NodeType.kOpticalStim

    def __init__(
        self, peripheral_id, bit_width, sample_rate, gain, channel_mask=ChannelMask()
    ):
        self.channel_mask = channel_mask
        self.peripheral_id = peripheral_id
        self.bit_width = bit_width
        self.sample_rate = sample_rate
        self.gain = gain

    def _to_proto(self):
        n = NodeConfig()
        p = OpticalStimConfig()
        p.peripheral_id = self.peripheral_id
        for i in self.channel_mask.iter_channels():
            p.pixel_mask.append(i)
        p.bit_width = self.bit_width
        p.sample_rate = self.sample_rate
        p.gain = self.gain

        n.optical_stim.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[OpticalStimConfig]):
        if proto is None:
            return OpticalStimulation()

        if not isinstance(proto, OpticalStimConfig):
            raise ValueError("proto is not of type OpticalStimConfig")

        new_node = OpticalStimulation(
            proto.peripheral_id,
            proto.bit_width,
            proto.sample_rate,
            proto.gain,
            ChannelMask(proto.pixel_mask),
        )
        return new_node
