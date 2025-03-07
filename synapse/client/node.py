from synapse.api.node_pb2 import NodeConfig, NodeType


class Node(object):
    id: int = None
    type: NodeType = NodeType.kNodeTypeUnknown
    device = None

    def __init__(self):
        pass

    def to_proto(self):
        proto = self._to_proto()
        proto.id = self.id
        proto.type = self.type
        return proto

    def _to_proto(self):
        raise NotImplementedError

    @staticmethod
    def _from_proto(_):
        raise NotImplementedError

    @classmethod
    def from_proto(cls, proto: NodeConfig):
        config = None

        oneof = proto.WhichOneof("config")
        if oneof and hasattr(proto, oneof):
            config = getattr(proto, oneof)
        node = cls._from_proto(config)
        node.id = proto.id
        return node
