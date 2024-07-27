import socket
import time
from typing import Optional
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_in_pb2 import StreamInConfig

MULTICAST_TTL = 3

class StreamIn(Node):
    type = NodeType.kStreamIn

    def __init__(self):
        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    def write(self, data):
        if self.device is None:
            return False

        node_socket = next((s for s in self.device.sockets if s.node_id == self.id), None)

        if node_socket is None:
            return False

        [_, port] = node_socket.bind.split(":")
        addr = self._get_addr()
        if addr is None:
            return False
        port = int(port)
        
        try:
            self.__socket.sendto(data, (addr, port))
            # https://stackoverflow.com/questions/21973661/os-x-udp-send-error-55-no-buffer-space-available
            time.sleep(0.00001)
        except Exception as e:
            print(f"Error sending data: {e}")
        return True

    def _to_proto(self):
        n = NodeConfig()
        i = StreamInConfig()
        i.shape.append(2048)
        i.shape.append(1)

        n.stream_in.CopyFrom(i)
        return n

    def _get_addr(self):
        if self.device is None:
            return None

        if self.__multicast_group:
            return self.__multicast_group
        
        return self.device.uri.split(":")[0]
    
    @staticmethod
    def _from_proto(proto: Optional[StreamInConfig]):
        if proto is None:
            return StreamIn()

        if not isinstance(proto, StreamInConfig):
            raise ValueError("proto is not of type StreamInConfig")

        return StreamIn()
