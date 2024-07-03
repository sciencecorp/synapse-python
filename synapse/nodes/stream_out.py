import socket
import struct
from synapse import ChannelMask
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_out_pb2 import StreamOutConfig

class StreamOut(Node):
    def __init__(self, channel_mask=ChannelMask()):
        self.__socket = None
        self.channel_mask = channel_mask

    def read(self):
        if self.device is None:
            return False

        node_socket = next((s for s in self.device.sockets if s.node_id == self.id), None)
        if node_socket is None:
            return False
        
        [group, p] = node_socket.bind.split(":")
        port = int(p)

        if self.__socket is None:
            self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            self.__socket.bind((group, port))

            host = socket.gethostbyname(socket.gethostname())
            mreq = socket.inet_aton(group) + socket.inet_aton(host)

            mreq = struct.pack("4sL", socket.inet_aton(group), socket.INADDR_ANY)
            self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        data, _ = self.__socket.recvfrom(1024)
        return data

    def to_proto(self):
        n = NodeConfig()
        n.type = NodeType.kStreamOut
        n.id = self.id

        o = StreamOutConfig()
        for i in self.channel_mask.iter_channels():
            o.ch_mask.append(i)

        n.stream_out.CopyFrom(o)
        return n
