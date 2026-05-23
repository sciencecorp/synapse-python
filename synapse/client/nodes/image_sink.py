from typing import Optional

from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.image_sink_pb2 import ImageSinkConfig
from synapse.client.node import Node


class ImageSink(Node):
    type = NodeType.kImageSink

    def __init__(
        self,
        peripheral_id: int,
        frame_rate_hz: int,
    ):
        self.peripheral_id: int = peripheral_id
        self.frame_rate_hz: int = frame_rate_hz

    def _to_proto(self):
        n = NodeConfig()
        p = ImageSinkConfig(
            peripheral_id=self.peripheral_id,
            frame_rate_hz=self.frame_rate_hz,
        )
        n.image_sink.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[ImageSinkConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, ImageSinkConfig):
            raise ValueError("proto is not of type ImageSinkConfig")

        return ImageSink(
            peripheral_id=proto.peripheral_id,
            frame_rate_hz=proto.frame_rate_hz,
        )
