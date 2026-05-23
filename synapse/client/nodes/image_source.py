from typing import Optional

from synapse.api.datatype_pb2 import PixelFormat
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.image_source_pb2 import ImageSourceConfig
from synapse.client.node import Node


class ImageSource(Node):
    type = NodeType.kImageSource

    def __init__(
        self,
        peripheral_id: int,
        width: int,
        height: int,
        format: PixelFormat,
        frame_rate_hz: int,
    ):
        self.peripheral_id: int = peripheral_id
        self.width: int = width
        self.height: int = height
        self.format: PixelFormat = format
        self.frame_rate_hz: int = frame_rate_hz

    def _to_proto(self):
        n = NodeConfig()
        p = ImageSourceConfig(
            peripheral_id=self.peripheral_id,
            width=self.width,
            height=self.height,
            format=self.format,
            frame_rate_hz=self.frame_rate_hz,
        )
        n.image_source.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[ImageSourceConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, ImageSourceConfig):
            raise ValueError("proto is not of type ImageSourceConfig")

        return ImageSource(
            peripheral_id=proto.peripheral_id,
            width=proto.width,
            height=proto.height,
            format=proto.format,
            frame_rate_hz=proto.frame_rate_hz,
        )
