from synapse.node import Node
from generated.api.node_pb2 import NodeOptions, NodeType
from generated.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig

class ElectricalBroadband(Node):
  def __init__(self, channel_mask):
    self.channel_mask = channel_mask

  def to_proto(self):
    n = NodeOptions()
    n.type = NodeType.kElectricalBroadband
    n.id = self.id

    p = ElectricalBroadbandConfig()
    p.peripheral_id = 0
    for i in self.channel_mask.iter_channels():
      p.ch_mask.append(i)
    p.bit_width = 10
    p.sample_rate = 20000
    p.gain = 1
    
    n.electrical_broadband.CopyFrom(p)
    return n