import queue
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.optical_stimulation_pb2 import OpticalStimulationConfig


class OpticalStimulation(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kOpticalStimulation)
        self.__config = None

    def config(self):
        c = super().config()
        if self.__config:
            c.optical_stimulation.CopyFrom(self.__config)
        return c

    def configure(self, config=OpticalStimulationConfig()) -> Status:
        self.__config = config
        return Status()

    async def run(self):
        self.logger.debug("Starting to receive data...")
        while self.running:
            data = await self.data_queue.get()

            # write to the device somehow, but here, just log it
            value = int.from_bytes(data, byteorder="big")
            self.logger.debug("received data: %i" % (self.id, value))

        self.logger.debug("exited thread")
