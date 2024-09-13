import logging
from typing import Tuple
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeConfig, NodeType, NodeSocket
from synapse.server.status import Status


class BaseNode(object):
    def __init__(self, id, type) -> None:
        self.id: int = id
        self.type: NodeType = type
        self.socket: Tuple[str, int] = None
        self.logger = logging.getLogger(f"[{self.__class__.__name__} id: {self.id}]")

    def config(self) -> NodeConfig:
        return NodeConfig(
            id=self.id,
            type=self.type,
        )

    def configure(self, config) -> Status:
        raise NotImplementedError

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def on_data_received(self):
        pass

    def emit_data(self, data):
        pass

    def node_socket(self):
        if self.socket is None:
            return False

        return NodeSocket(
            node_id=self.id,
            data_type=DataType.kAny,
            bind=f"{self.socket[0]}:{self.socket[1]}",
            type=self.type,
        )
