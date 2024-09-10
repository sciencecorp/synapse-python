import random
import logging
import threading
from synapse.server.nodes import BaseNode
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig


class ElectricalBroadband(BaseNode):

    def __init__(self, id):
        super().__init__(id, NodeType.kElectricalBroadband)
        self.stop_event = threading.Event()
   
    def configure(self, config = ElectricalBroadbandConfig()):
        pass

    def start(self):
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        logging.info("ElectricalBroadband (node %d): started" % self.id)

    def stop(self):
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return
        logging.info("ElectricalBroadband (node %d): stopping..." % self.id)
        self.stop_event.set()
        self.thread.join()
        logging.info("ElectricalBroadband (node %d): stopped" % self.id)

    def run(self):
        while not self.stop_event.is_set():
            data = random.randint(0, 100).to_bytes(4, byteorder="big")
            self.emit_data(data)
