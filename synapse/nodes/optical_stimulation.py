from synapse.node import Node
from synapse.generated.api.node_pb2 import NodeConfig, NodeType
from synapse.generated.api.nodes.optical_stim_pb2 import OpticalStimConfig


class OpticalStimulation(Node):
    def __init__(self, channel_mask):
        self.channel_mask = channel_mask

    def to_proto(self):
        n = NodeConfig()
        n.type = NodeType.kOpticalStim
        n.id = self.id

        p = OpticalStimConfig()
        p.peripheral_id = 0
        for i in self.channel_mask.iter_channels():
            p.pixel_mask.append(i)
        p.bit_width = 10
        p.sample_rate = 20000
        p.gain = 1

        n.optical_stim.CopyFrom(p)
        return n
