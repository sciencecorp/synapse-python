from synapse.api.node_pb2 import NodeType
from synapse.server.nodes.base import BaseNode
from synapse.server.nodes.stream_in import StreamIn
from synapse.server.nodes.stream_out import StreamOut
from synapse.server.nodes.spectral_filter import SpectralFilter

SERVER_NODE_OBJECT_MAP = {
    NodeType.kStreamIn: StreamIn,
    NodeType.kStreamOut: StreamOut,
    NodeType.kSpectralFilter: SpectralFilter,
}
