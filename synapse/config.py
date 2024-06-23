class Config(object):
  nodes = []
  connections = []

  def __init__(self):
    pass

  def _gen_node_id(self):
    return len(self.nodes)

  def add(self, node):
    node.id = self._gen_node_id()
    self.nodes.append(node)
    return True

  def connect(self, from_node, to_node):
    if from_node.id is None or to_node.id is None:
      return False
    
    self.connections.append((from_node.id, to_node.id))
    
    return True