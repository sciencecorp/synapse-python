from synapse import ChannelMask
from synapse.node import Node
from synapse.generated.api.node_pb2 import NodeConfig, NodeType
from synapse.generated.api.nodes.stream_in_pb2 import StreamInConfig


class StreamIn(Node):
    def __init__(self):
        pass

    def write(self):
        if self.device is None:
            return False
        return True

    def to_proto(self):
        n = NodeConfig()
        n.type = NodeType.kStreamIn
        n.id = self.id

        o = StreamInConfig()
        o.shape.append(2048)
        o.shape.append(1)

        n.stream_in.CopyFrom(o)
        return n
