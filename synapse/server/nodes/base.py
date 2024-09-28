import logging
import queue
import threading
from typing import Tuple

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeConfig, NodeSocket, NodeType
from synapse.server.status import Status
from synapse.utils.datatypes import SynapseData


class BaseNode(object):
    def __init__(self, id, type) -> None:
        self.id: int = id
        self.type: NodeType = type
        self.socket: Tuple[str, int] = None
        self.logger = logging.getLogger(f"[{self.__class__.__name__} id: {self.id}]")
        self.data_queue = queue.Queue()

    def config(self) -> NodeConfig:
        return NodeConfig(
            id=self.id,
            type=self.type,
        )

    def configure(self, config) -> Status:
        raise NotImplementedError

    def start(self):
        self.logger.info("starting...")
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.info("started")
        return Status()

    def stop(self):
        self.logger.info("stopping...")
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return

        self.stop_event.set()
        self.thread.join()
        self.logger.info("stopped")
        return Status()

    def on_data_received(self, data: SynapseData):
        self.data_queue.put(data)

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
