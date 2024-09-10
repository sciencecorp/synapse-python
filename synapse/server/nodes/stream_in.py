import logging
import select
import socket
import threading
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_in_pb2 import StreamInConfig
from synapse.server.nodes import BaseNode
from synapse.server.status import Status


class StreamIn(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kStreamIn)
        self.__socket = None
        self.__stop_event = threading.Event()

    def config(self):
        c = super().config()

        i = StreamInConfig()
        i.data_type = self.data_type
        i.shape.extend(self.shape)

        c.stream_in.CopyFrom(i)
        return c

    def configure(self, config: StreamInConfig) -> Status:
        self.data_type = config.data_type
        self.shape = config.shape

        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 3)

        self.__socket.bind(("", 0))
        self.socket = self.__socket.getsockname()
        self.logger.info(f"listening on {self.socket}")

        return Status()

    def start(self) -> Status:
        self.logger.info("starting...")
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.info("started")
        return Status()

    def stop(self) -> Status:
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return
        self.logger.info("stopping...")
        self.__stop_event.set()
        self.thread.join()
        self.__socket.close()
        self.__socket = None
        self.logger.info("stopped")
        return Status()

    def run(self):
        self.logger.info("starting to receive data...")
        while not self.__stop_event.is_set():
            try:
                ready = select.select([self.__socket], [], [], 1)
                if ready[0]:
                    data, _ = self.__socket.recvfrom(1024)
                    self.emit_data(data)
            except Exception as e:
                self.logger.error(f"Error receiving data: {e}")

        self.logger.info("exited thread")
