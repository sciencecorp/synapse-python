import socket
import time
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_in_pb2 import StreamInConfig

MULTICAST_TTL = 3

class StreamIn(Node):
    def __init__(self, multicast_group=None):
        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        self.__multicast_group = multicast_group

    def write(self, data):
        if self.device is None:
            return False

        socket = next((s for s in self.device.sockets if s.node_id == self.id), None)

        if socket is None:
            return False

        [group, p] = socket.bind.split(":")
        port = int(p)

        try:
            self.__socket.sendto(data, (group, port))
            # https://stackoverflow.com/questions/21973661/os-x-udp-send-error-55-no-buffer-space-available
            time.sleep(0.00001)
        except Exception as e:
            print(f"Error sending data: {e}")
        return True

    def to_proto(self):
        n = NodeConfig()
        n.type = NodeType.kStreamIn
        n.id = self.id

        i = StreamInConfig()
        i.shape.append(2048)
        i.shape.append(1)
        if self.__multicast_group:
            i.multicast_group = self.__multicast_group

        n.stream_in.CopyFrom(i)
        return n
