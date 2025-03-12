import asyncio
import socket
from typing import List

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_out_pb2 import StreamOutConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import SynapseData


class StreamOut(BaseNode):
    __n = 0

    def __init__(self, id):
        super().__init__(id, NodeType.kStreamOut)
        self.__i = StreamOut.__n
        StreamOut.__n += 1
        self.__sequence_number = 0
        self.__config = None
        self.socket_endpoint = None

    def config(self):
        c = super().config()

        if self.__config:
            c.stream_out.CopyFrom(self.__config)

        return c

    def configure(self, config: StreamOutConfig) -> Status:
        self.__config = config

        if not config.udp_unicast:
            self.logger.error(
                "Cannot conifgure StreamOut, only udp unicast is supported"
            )
            raise Exception("Only udp unicast is supported for streamout")

        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        dest_address = self.__config.udp_unicast.destination_address
        dest_port = self.__config.udp_unicast.destination_port
        self.socket_endpoint = (dest_address, dest_port)
        self.logger.info(f"created stream out socket on {self.__socket}")

        return Status()

    async def run(self):
        loop = asyncio.get_running_loop()
        while self.running:
            if not self.socket_endpoint:
                self.logger.error("socket not configured")
                return

            data = await self.data_queue.get()
            packets = self._pack(data)

            for packet in packets:
                await loop.run_in_executor(
                    None,
                    self.__socket.sendto,
                    packet,
                    self.socket_endpoint,
                )

    def _pack(self, data: SynapseData) -> List[bytes]:
        packets = []

        try:
            packets, seq = data.pack(self.__sequence_number)
            self.__sequence_number = seq
        except Exception as e:
            raise ValueError(f"Error packing data: {e}")

        return packets
