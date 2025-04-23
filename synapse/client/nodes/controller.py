from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.client.node import Node
from synapse.api.nodes.controller_pb2 import ControllerNodeConfig


class Controller(Node):
    type = NodeType.kController

    def __init__(self):
        pass

    def _to_proto(self):
        n = NodeConfig()
        p = ControllerNodeConfig()
        n.controller.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[ControllerNodeConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, ControllerNodeConfig):
            raise ValueError("proto is not of type SpikeBinnerConfig")

        return Controller()
