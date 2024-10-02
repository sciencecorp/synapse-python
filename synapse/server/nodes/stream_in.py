import select
import socket

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_in_pb2 import StreamInConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status

from synapse.utils.ndtp_types import SynapseData


class StreamIn(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kStreamIn)

    def config(self):
        c = super().config()

        if self.__config:
            c.stream_in.CopyFrom(self.__config)

        return c

    def configure(self, config: StreamInConfig) -> Status:
        self.__config = config

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

    def configure_iface_ip(self, iface_ip):
        pass

    async def run(self):
        self.logger.info("starting to receive data...")
        while self.running:
            try:
                ready = select.select([self.__socket], [], [], 1)
                if ready[0]:
                    data, _ = self.__socket.recvfrom(1024)
                    unpacked = self._unpack(data)
                    await self.emit_data(unpacked)
            except Exception as e:
                self.logger.error(f"Error receiving data: {e}")

        self.logger.info("exited thread")

    def _unpack(self, data: bytes) -> SynapseData:
        # TODO: fill this in using NDTP
        return data
