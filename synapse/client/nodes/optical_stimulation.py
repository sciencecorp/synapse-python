from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.optical_stimulation_pb2 import OpticalStimulationConfig
from synapse.client.node import Node


class OpticalStimulation(Node):
    type = NodeType.kOpticalStimulation

    def __init__(
        self, peripheral_id, pixel_mask, bit_width, sample_rate, gain
    ):
        self.pixel_mask = pixel_mask
        self.peripheral_id = peripheral_id
        self.bit_width = bit_width
        self.sample_rate = sample_rate
        self.gain = gain

    def _to_proto(self):
        n = NodeConfig()
        p = OpticalStimulationConfig()
        p.peripheral_id = self.peripheral_id
        for i in self.pixel_mask.iter_channels():
            p.pixel_mask.append(i)
        p.bit_width = self.bit_width
        p.sample_rate = self.sample_rate
        p.gain = self.gain

        n.optical_stimulation.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[OpticalStimulationConfig]):
        if proto is None:
            return OpticalStimulation()

        if not isinstance(proto, OpticalStimulationConfig):
            raise ValueError("proto is not of type OpticalStimulationConfig")

        new_node = OpticalStimulation(
            peripheral_id=proto.peripheral_id,
            pixel_mask=proto.pixel_mask,
            bit_width=proto.bit_width,
            sample_rate=proto.sample_rate,
            gain=proto.gain,
        )
        return new_node
