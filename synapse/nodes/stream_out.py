from synapse.node import Node
from generated.api.node_pb2 import NodeConfig, NodeType
from generated.api.nodes.stream_out_pb2 import StreamOutConfig

class StreamOut(Node):
  def __init__(self):
    pass

  def read(self):
    pass

  def to_proto(self):
    n = NodeConfig()
    n.type = NodeType.kStreamOut
    n.id = self.id

    o = StreamOutConfig()
    for i in self.channel_mask.iter_channels():
      o.ch_mask.append(i)

    n.stream_out.CopyFrom(o)
    return n