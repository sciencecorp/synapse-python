import asyncio
import queue
import socket
import struct
from typing import List

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_out_pb2 import StreamOutConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status, StatusCode
from synapse.utils.ndtp_types import SynapseData

PORT = 6480
MULTICAST_TTL = 3


class StreamOut(BaseNode):
    __n = 0

    def __init__(self, id):
        super().__init__(id, NodeType.kStreamOut)
        self.__i = StreamOut.__n
        StreamOut.__n += 1
        self.__sequence_number = 0
        self.__iface_ip = None
        self.__config = None

    def config(self):
        c = super().config()

        if self.__config:
            c.stream_out.CopyFrom(self.__config)

        return c

    def configure(self, config: StreamOutConfig) -> Status:
        if not self.__iface_ip:
            return Status(StatusCode.kUndefinedError, "No interface IP specified")

        if not config.multicast_group:
            return Status(StatusCode.kUndefinedError, "No multicast group specified")

        self.__config = config

        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        port = PORT + self.__i

        self.__socket.bind((self.__iface_ip, port))

        mreq = struct.pack(
            "=4sl", socket.inet_aton(config.multicast_group), socket.INADDR_ANY
        )
        self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.__socket.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL
        )

        self.socket = [config.multicast_group, port]
        self.logger.info(
            f"created multicast socket on {self.socket}, group {config.multicast_group}"
        )

        return Status()

    def configure_iface_ip(self, iface_ip):
        self.__iface_ip = iface_ip

    async def run(self):
        loop = asyncio.get_running_loop()
        while self.running:
            if not self.socket:
                self.logger.error("socket not configured")
                return
            try:
                data = self.data_queue.get(True, 1)
            except queue.Empty:
                continue

            packets = self._pack(data)

            for packet in packets:
                try:
                    await loop.run_in_executor(
                        None,
                        self.__socket.sendto,
                        packet,
                        (self.socket[0], self.socket[1]),
                    )
                except Exception as e:
                    self.logger.error(f"Error sending data: {e}")

    def _pack(self, data: SynapseData) -> List[bytes]:
        packets = []

        if hasattr(data, "pack"):
            try:
                packets = data.pack(self.__sequence_number)
                self.__sequence_number += len(packets)

            except Exception as e:
                raise ValueError(f"Error packing data: {e}")
        else:
            raise ValueError(f"Invalid payload: {type(data)}, {data}")

        return packets
