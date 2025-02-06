from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.api.node_pb2 import NodeConnection
from synapse.client.nodes import NODE_TYPE_OBJECT_MAP


class Config(object):
    nodes = []
    connections = []

    def __init__(self):
        pass

    def _gen_node_id(self):
        return len(self.nodes) + 1

    def add(self, nodes):
        for node in nodes:
            if not self.add_node(node):
                return False
        return True

    def get_node(self, node_id):
        return next((node for node in self.nodes if node.id == node_id), None)

    def add_node(self, node):
        if node.id:
            return False
        node.id = self._gen_node_id()
        self.nodes.append(node)
        return True

    def set_device(self, device):
        for node in self.nodes:
            node.device = device

    def connect(self, src, dst):
        if not src.id or not dst.id:
            return False
        self.connections.append((src.id, dst.id))
        return True

    def to_proto(self):
        c = DeviceConfiguration()
        for node in self.nodes:
            c.nodes.append(node.to_proto())
        for connection in self.connections:
            x = NodeConnection()
            x.src_node_id = connection[0]
            x.dst_node_id = connection[1]
            c.connections.append(x)
        return c

    @staticmethod
    def from_proto(proto):
        config = Config()

        for n in proto.nodes:
            if n.type not in list(NODE_TYPE_OBJECT_MAP.keys()):
                print(f"Unknown node type: {n.type}")
                continue
            node = NODE_TYPE_OBJECT_MAP[n.type].from_proto(n)

            if not node.id:
                config.add_node(node)
            else:
                config.nodes.append(node)

        for c in proto.connections:
            src = next((n for n in config.nodes if n.id == c.src_node_id), None)
            dst = next((n for n in config.nodes if n.id == c.dst_node_id), None)
            if src is None or dst is None:
                continue
            config.connect(src, dst)

        return config
