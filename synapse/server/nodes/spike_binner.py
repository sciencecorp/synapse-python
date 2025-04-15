from collections import defaultdict

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_binner_pb2 import SpikeBinnerConfig
from synapse.server.nodes import BaseNode
from synapse.server.status import Status

class SpikeBinner(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeBinner)
        self.bin_size_ms = None

    def config(self):
        c = super().config()
        c.spike_binner.bin_size_ms = self.bin_size_ms
        return c

    def configure(self, config=SpikeBinnerConfig()):
        self.bin_size_ms = config.bin_size_ms
        
        return Status()

    async def run(self):
        while self.running:
            data = await self.data_queue.get()

            if data.data_type != DataType.kBroadband:
                self.logger.warning("Received non-broadband data")
                continue
