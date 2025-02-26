
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.disk_writer_pb2 import DiskWriterConfig
from synapse.client.node import Node

class DiskWriter(Node):
    type = NodeType.kDiskWriter

    def __init__(self, filename: str):
        self.filename = filename

    def _to_proto(self):
        n = NodeConfig()
        p = DiskWriterConfig(filename=self.filename)
        n.disk_writer.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: DiskWriterConfig):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, DiskWriterConfig):
            raise ValueError("proto is not of type DiskWriterConfig")

        return DiskWriter(filename=proto.filename)