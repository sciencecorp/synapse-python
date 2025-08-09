from synapse.api.node_pb2 import NodeType
from synapse.server.nodes.spectral_filter import SpectralFilter

SERVER_NODE_OBJECT_MAP = {
    NodeType.kSpectralFilter: SpectralFilter,
}
