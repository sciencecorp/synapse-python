import logging
import queue
import socket
import threading
from synapse.server.nodes import BaseNode
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_out_pb2 import StreamOutConfig

PORT = 6480
MULTICAST_TTL = 3


class StreamOut(BaseNode):
    __n = 0

    def __init__(self, id):
        super().__init__(id, NodeType.kStreamOut)
        self.__i = StreamOut.__n
        StreamOut.__n += 1
        self.__stop_event = threading.Event()
        self.__data_queue = queue.Queue()

    def config(self):
        c = super().config()

        o = StreamOutConfig()

        if self.multicastGroup:
            o.multicast_group = self.multicastGroup
            o.use_multicast = True
        c.stream_out.CopyFrom(o)
        return c

    def configure(self, config: StreamOutConfig):
        self.multicastGroup: str = config.multicast_group if config.use_multicast else None

        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        port = PORT + self.__i

        if config.multicast_group:
            self.multicastGroup = config.multicast_group
            self.__socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL
            )

            self.socket = [self.multicastGroup, port]

            logging.info(
                f"StreamOut (node {self.id}): created multicast socket on {self.socket}, group {self.multicastGroup}"
            )

        else:
            self.socket = [self.__socket.getsockname()[0], port]

            logging.info(
                f"StreamOut (node {self.id}): created unicast socket on {self.socket}"
            )

        return True

    def start(self):
        logging.info("StreamOut (node %d): starting..." % self.id)

        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()

        logging.info("StreamOut (node %d): started" % self.id)

    def stop(self):
        logging.info("StreamOut (node %d): stopping..." % self.id)
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return

        self.__stop_event.set()
        self.thread.join()
        self.__socket.close()
        self.__socket = None
        logging.info("StreamOut (node %d): stopped" % self.id)

    def on_data_received(self, data):
        self.__data_queue.put(data)

    def run(self):
        logging.info("StreamOut (node %d): starting to send data..." % self.id)
        while not self.__stop_event.is_set():
            if not self.socket:
                logging.error("StreamOut (node %d): socket not configured" % self.id)
                return
            try:
                data = self.__data_queue.get(True, 1)
            except queue.Empty:
                continue
            try:
                addr = self.multicastGroup if self.multicastGroup else ""
                port = self.socket[1]
                self.__socket.sendto(data, (addr, port))
                if not self.socket:
                    self.socket = self.__socket.getsockname()

            except Exception as e:
                logging.error(f"Error sending data: {e}")
