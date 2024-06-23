from generated.api.synapse_pb2 import DeviceConfiguration
from generated.api.node_pb2 import NodeConnection

class Config(object):
  nodes = []
  connections = []

  def __init__(self):
    pass

  def _gen_node_id(self):
    return len(self.nodes) + 1

  def add(self, nodes):
    for node in nodes:
      if not self.add_node(node):
        return False
    return True
  
  def add_node(self, node):
    if node.id is not None:
      return False
    node.id = self._gen_node_id()
    self.nodes.append(node)
    return True

  def set_device(self, device):
    for node in self.nodes:
      node.device = device

  def connect(self, from_node, to_node):
    if from_node.id is None or to_node.id is None:
      return False
    self.connections.append((from_node.id, to_node.id))  
    return True
  
  def to_proto(self):
    c = DeviceConfiguration()
    for node in self.nodes:
      c.nodes.append(node.to_proto())
    for connection in self.connections:
      x = NodeConnection()
      x.src_node_id = connection[0]
      x.dst_node_id = connection[1]
      c.connections.append(x)
    return c