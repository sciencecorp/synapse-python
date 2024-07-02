import zmq
from synapse import ChannelMask
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_out_pb2 import StreamOutConfig


class StreamOut(Node):
    def __init__(self, channel_mask=None):
        self.zmq_context = zmq.Context()
        self.zmq_socket = None

        # if from_proto is not None:
        if channel_mask is None:
            self.channel_mask = ChannelMask("all")
        else:
            self.channel_mask = channel_mask

    def read(self):
        if self.device is None:
            return False

        socket = next((s for s in self.device.sockets if s.node_id == self.id), None)
        if socket is None:
            return False

        if not self.zmq_socket:
            self.zmq_socket = self.zmq_context.socket(zmq.DISH)
            self.zmq_socket.rcvtimeo = 1000
            self.zmq_socket.bind(f"udp://{socket.bind}")
            self.zmq_socket.join('stream_out')

        data = self.zmq_socket.recv(copy=False)
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
