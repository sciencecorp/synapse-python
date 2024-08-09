import socket
import struct
from typing import Optional
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_out_pb2 import StreamOutConfig


class StreamOut(Node):
    type = NodeType.kStreamOut

    def __init__(self, label=None, multicast_group=None):
        self.__socket = None
        self.__label = label
        self.__multicast_group: Optional[str] = multicast_group

    def read(self) -> Optional[bytes]:
        if self.__socket is None:
            if self.device is None:
                return None

            node_socket = next(
                (s for s in self.device.sockets if s.node_id == self.id), None
            )
            if node_socket is None:
                return None

            bind = node_socket.bind.split(":")
            if len(bind) != 2:
                return False

            addr = self.__multicast_group if self.__multicast_group else bind[0]
            if addr is None:
                return None

            port = int(bind[1])
            if not port:
                return None 

            self.__socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.__socket.setblocking(1)

            self.__socket.bind((addr, port))

            if self.__multicast_group:
                host = socket.gethostbyname(socket.gethostname())
                mreq = socket.inet_aton(addr) + socket.inet_aton(host)

                mreq = struct.pack("4sL", socket.inet_aton(addr), socket.INADDR_ANY)
                self.__socket.setsockopt(
                    socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq
                )

        data, _ = self.__socket.recvfrom(4096)
        return data

    def _to_proto(self):
        n = NodeConfig()

        o = StreamOutConfig()

        if self.__label:
            o.label = self.__label

        if self.__multicast_group:
            o.multicast_group = self.__multicast_group
            o.use_multicast = (
                self.__multicast_group is not None and len(self.__multicast_group) > 0
            )

        n.stream_out.CopyFrom(o)
        return n

    @staticmethod
    def _from_proto(proto: Optional[StreamOutConfig]):
        if proto is None:
            return StreamOut()

        if not isinstance(proto, StreamOutConfig):
            raise ValueError("proto is not of type StreamOutConfig")

        return StreamOut(proto.label, proto.multicast_group)
