from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.application_pb2 import ApplicationNodeConfig
from synapse.client.node import Node


class ApplicationNode(Node):
    type = NodeType.kApplication

    def __init__(self, name: str):
        self.name = name

    def _to_proto(self):
        n = NodeConfig()
        p = ApplicationNodeConfig(name=self.name)
        n.application.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: ApplicationNodeConfig):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, ApplicationNodeConfig):
            raise ValueError("proto is not of type ApplicationNodeConfig")

        return ApplicationNode(name=proto.name)
