import asyncio
import logging
from typing import List, Tuple

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeConfig, NodeSocket, NodeType
from synapse.server.status import Status
from synapse.utils.ndtp_types import SynapseData


class BaseNode(object):
    def __init__(self, id, type) -> None:
        self.id: int = id
        self.type: NodeType = type
        self.socket: Tuple[str, int] = None
        self.logger = logging.getLogger(f"[{self.__class__.__name__} id: {self.id}]")
        self.data_queue = asyncio.Queue()
        self.downstream_nodes = []
        self.running = False
        self.tasks: List[asyncio.Task] = []

    def config(self) -> NodeConfig:
        return NodeConfig(
            id=self.id,
            type=self.type,
        )

    def configure(self, config) -> Status:
        raise NotImplementedError

    def add_downstream_node(self, node):
        self.downstream_nodes.append(node)

    def start(self):
        self.logger.info("starting...")
        if self.running:
            return Status()

        self.running = True
        task = asyncio.create_task(self.run())
        self.tasks.append(task)
        self.logger.info("started")
        return Status()

    def stop(self):
        self.logger.info("stopping...")
        if not self.running:
            return Status()

        self.running = False
        for task in self.tasks:
            task.cancel()
        self.tasks = []
        self.logger.info("Stopped")
        return Status()

    async def on_data_received(self, data: SynapseData):
        await self.data_queue.put(data)

    async def emit_data(self, data):
        for node in self.downstream_nodes:
            asyncio.create_task(node.on_data_received(data))

    def node_socket(self):
        if self.socket is None:
            return False

        return NodeSocket(
            node_id=self.id,
            data_type=DataType.kAny,
            bind=f"{self.socket[0]}:{self.socket[1]}",
            type=self.type,
        )
