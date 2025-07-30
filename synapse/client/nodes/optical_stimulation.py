from typing import Optional, List
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.optical_stimulation_pb2 import OpticalStimulationConfig
from synapse.client.node import Node


class OpticalStimulation(Node):
    type = NodeType.kOpticalStimulation

    def __init__(
        self, peripheral_id: int, pixel_mask: List[int], bit_width: int, frame_rate: int, gain: float, send_receipts: bool = False
    ):
        self.pixel_mask = pixel_mask
        self.peripheral_id = peripheral_id
        self.bit_width = bit_width
        self.frame_rate = frame_rate
        self.gain = gain
        self.send_receipts = send_receipts

    def _to_proto(self):
        n = NodeConfig()
        p = OpticalStimulationConfig()
        p.peripheral_id = self.peripheral_id
        p.pixel_mask.extend(self.pixel_mask)
        p.bit_width = self.bit_width
        p.frame_rate = self.frame_rate
        p.gain = self.gain
        p.send_receipts = self.send_receipts
        n.optical_stimulation.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[OpticalStimulationConfig]):
        if proto is None:
            return OpticalStimulation(0, [], 0, 0, 0.0, False)

        if not isinstance(proto, OpticalStimulationConfig):
            raise ValueError("proto is not of type OpticalStimulationConfig")

        return OpticalStimulation(
            peripheral_id=proto.peripheral_id,
            pixel_mask=list(proto.pixel_mask),
            bit_width=proto.bit_width,
            frame_rate=proto.frame_rate,
            gain=proto.gain,
            send_receipts=proto.send_receipts
        )
