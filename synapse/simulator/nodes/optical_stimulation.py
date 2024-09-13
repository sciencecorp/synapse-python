import queue
import threading
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.optical_stim_pb2 import OpticalStimConfig


class OpticalStimulation(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kOpticalStim)
        self.stop_event = threading.Event()
        self.data_queue = queue.Queue()
        self.__config = None

    def config(self):
        c = super().config()
        if self.__config:
            c.opticalStim.CopyFrom(self.__config)
        return c

    def configure(self, config = OpticalStimConfig()) -> Status:
        self.__config = config
        return Status()

    def start(self):
        self.logger.debug("starting...")
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.debug("started")

    def stop(self):
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return
        self.logger.debug("stopping...")
        self.stop_event.set()
        self.thread.join()
        self.logger.debug("stopped")

    def on_data_received(self, data):
        self.data_queue.put(data)

    def run(self):
        self.logger.debug(
            "Starting to receive data..."
        )
        while not self.stop_event.is_set():
            try:
                data = self.data_queue.get(True, 1)
            except queue.Empty:
                continue
            # write to the device somehow, but here, just log it
            value = int.from_bytes(data, byteorder="big")
            self.logger.debug("received data: %i" % (self.id, value))

        self.logger.debug("exited thread")
