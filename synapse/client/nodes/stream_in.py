import socket
import time
from typing import List, Optional
from synapse.client.node import Node
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.stream_in_pb2 import StreamInConfig
from synapse.utils.types import SynapseData

MULTICAST_TTL = 3


class StreamIn(Node):
    type = NodeType.kStreamIn

    def __init__(self, data_type: DataType, shape: List[int]):
        self.__sequence_number = 0
        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

    def write(self, data: SynapseData):
        if self.device is None:
            return False

        node_socket = next(
            (s for s in self.device.sockets if s.node_id == self.id), None
        )

        if node_socket is None:
            return False

        bind = node_socket.bind.split(":")
        if len(bind) != 2:
            return False

        host = bind[0]
        port = bind[1]
        if host is None:
            return False
        port = int(port)

        packets = self._pack(data)

        for packet in packets:
            try:
                self.__socket.sendto(packet, (host, port))
                # https://stackoverflow.com/questions/21973661/os-x-udp-send-error-55-no-buffer-space-available
                time.sleep(0.00001)
            except Exception as e:
                print(f"Error sending data: {e}")
        return True

    def _pack(self, data: SynapseData) -> List[bytes]:
        packets = []
        if type(data) == ElectricalBroadbandData:
            packets.append(data.pack(self.__sequence_number))
            self.__sequence_number = (self.__sequence_number + 1) & 0xFFFF

        elif type(data) == SpiketrainData:
            packets.append(data.pack(self.__sequence_number))
            self.__sequence_number = (self.__sequence_number + 1) & 0xFFFF

        elif type(data) == bytes:
            packets.append(data)
            self.__sequence_number = (self.__sequence_number + 1) & 0xFFFF

        else:
            raise ValueError(f"Unknown data type: {type(data)}")

        return packets

    def _to_proto(self):
        n = NodeConfig()
        i = StreamInConfig()
        i.shape.append(2048)
        i.shape.append(1)

        n.stream_in.CopyFrom(i)
        return n

    @staticmethod
    def _from_proto(proto: Optional[StreamInConfig]):
        if proto is None:
            return StreamIn()

        if not isinstance(proto, StreamInConfig):
            raise ValueError("proto is not of type StreamInConfig")

        return StreamIn()
