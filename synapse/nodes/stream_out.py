import zmq
from synapse import ChannelMask
from synapse.node import Node
from generated.api.node_pb2 import NodeConfig, NodeType
from generated.api.nodes.stream_out_pb2 import StreamOutConfig

class StreamOut(Node):
  def __init__(self, channel_mask=None):
    self.zmq_context = zmq.Context()

    if channel_mask is None:
      self.channel_mask = ChannelMask("all")
    else:
      self.channel_mask = channel_mask

  def read(self):
    if self.device is None:
      return False
    for socket in self.device.sockets:
      if socket.node_id == self.id:
        zmq_socket = zmq.Socket(self.zmq_context, zmq.SUB)
        zmq_socket.connect(socket.bind)
        zmq_socket.setsockopt(zmq.SUBSCRIBE, b'')
        return zmq_socket.recv()
    return None

  def to_proto(self):
    n = NodeConfig()
    n.type = NodeType.kStreamOut
    n.id = self.id

    o = StreamOutConfig()
    for i in self.channel_mask.iter_channels():
      o.ch_mask.append(i)

    n.stream_out.CopyFrom(o)
    return n