import socket
import struct
from synapse import ChannelMask
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_out_pb2 import StreamOutConfig

class StreamOut(Node):
    def __init__(self, bind, channel_mask=ChannelMask(), multicast_group=None):
        self.__socket = None
        self.__bind = bind
        self.__channel_mask = channel_mask
        self.__multicast_group = multicast_group  

    def read(self):
        if self.device is None:
            print("Device not set")
            return False

        node_socket = next((s for s in self.device.sockets if s.node_id == self.id), None)
        if node_socket is None:
            print("Node socket not found")
            return False
        
        addr = self.__multicast_group
        port = node_socket.bind

        if self.__socket is None:
            self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            self.__socket.bind((addr, port))

            if self.__multicast_group:
                host = socket.gethostbyname(socket.gethostname())
                mreq = socket.inet_aton(addr) + socket.inet_aton(host)

                mreq = struct.pack("4sL", socket.inet_aton(addr), socket.INADDR_ANY)
                self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        data, _ = self.__socket.recvfrom(1024)
        return data

    def to_proto(self):
        n = NodeConfig()
        n.type = NodeType.kStreamOut
        n.id = self.id

        o = StreamOutConfig()
        for i in self.__channel_mask.iter_channels():
            o.ch_mask.append(i)

        if self.__multicast_group:
            o.multicast_group = self.__multicast_group
        
        if self.__bind:
            o.bind = self.__bind

        n.stream_out.CopyFrom(o)
        return n
