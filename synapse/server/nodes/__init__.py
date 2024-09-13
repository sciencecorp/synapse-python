from synapse.api.node_pb2 import NodeType
from synapse.server.nodes.stream_in import StreamIn
from synapse.server.nodes.stream_out import StreamOut

SERVER_NODE_OBJECT_MAP = {
  NodeType.kStreamIn: StreamIn,
  NodeType.kStreamOut: StreamOut
}
