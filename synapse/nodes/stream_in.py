from synapse import ChannelMask
from synapse.node import Node
from synapse.api.api.node_pb2 import NodeConfig, NodeType
from synapse.api.api.nodes.stream_in_pb2 import StreamInConfig


class StreamIn(Node):
    def __init__(self):
        # ctx = zmq.Context.instance()
        # self.socket = zmq.Socket(ctx, zmq.PUB)
        pass

    def write(self, data):
        if self.device is None:
            return False

        socket = next((s for s in self.device.sockets if s.node_id == self.id), None)

        if socket is None:
            return False

        # self.socket.connect(socket.bind)
        try:
            # self.socket.send_string(data)
            pass
        except Exception as e:
            print(f"Error sending data: {e}")
        return True

    def to_proto(self):
        n = NodeConfig()
        n.type = NodeType.kStreamIn
        n.id = self.id

        o = StreamInConfig()
        o.shape.append(2048)
        o.shape.append(1)

        n.stream_in.CopyFrom(o)
        return n
