from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.optical_broadband_pb2 import OpticalBroadbandConfig
from synapse.client.node import Node

class OpticalBroadband(Node):
    type = NodeType.kOpticalBroadband

    def __init__(
        self,
        peripheral_id,
        pixel_mask,
        bit_width,
        frame_rate,
        gain
    ):
        self.peripheral_id = peripheral_id
        self.pixel_mask = pixel_mask
        self.bit_width = bit_width
        self.frame_rate = frame_rate
        self.gain = gain

    def _to_proto(self):
        n = NodeConfig()
        p = OpticalBroadbandConfig(
            peripheral_id=self.peripheral_id,
            pixel_mask=self.pixel_mask,
            bit_width=self.bit_width,
            frame_rate=self.frame_rate,
            gain=self.gain
        )
        n.optical_broadband.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[OpticalBroadbandConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, OpticalBroadbandConfig):
            raise ValueError("proto is not of type OpticalBroadbandConfig")

        return OpticalBroadband(
            peripheral_id=proto.peripheral_id,
            pixel_mask=proto.pixel_mask,
            bit_width=proto.bit_width,
            frame_rate=proto.frame_rate,
            gain=proto.gain
        )
