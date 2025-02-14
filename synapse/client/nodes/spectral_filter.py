from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.spectral_filter_pb2 import SpectralFilterConfig
from synapse.client.node import Node


class SpectralFilter(Node):
    type = NodeType.kSpectralFilter

    def __init__(self, method, low_cutoff_hz=None, high_cutoff_hz=None):
        self.method = method
        self.low_cutoff_hz = low_cutoff_hz
        self.high_cutoff_hz = high_cutoff_hz

    def _to_proto(self):
        n = NodeConfig()
        p = SpectralFilterConfig(
            method=self.method,
            low_cutoff_hz=self.low_cutoff_hz,
            high_cutoff_hz=self.high_cutoff_hz,
        )
        n.spectral_filter.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[SpectralFilterConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, SpectralFilterConfig):
            raise ValueError("proto is not of type SpectralFilterConfig")

        return SpectralFilter(
            proto.method,
            proto.low_cutoff_hz,
            proto.high_cutoff_hz,
        )