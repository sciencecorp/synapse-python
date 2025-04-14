from typing import Optional, List
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.spike_binner_pb2 import SpikeBinnerConfig
from synapse.client.node import Node


class SpikeBinner(Node):
    type = NodeType.kSpikeBinner

    def __init__(
        self,
        bin_size_ms: int = None,
    ):
        self.bin_size_ms = bin_size_ms

    def _to_proto(self):
        n = NodeConfig()
        p = SpikeBinnerConfig(
            bin_size_ms=self.bin_size_ms,
        )
        n.spike_binner.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[SpikeBinnerConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, SpikeBinnerConfig):
            raise ValueError("proto is not of type SpikeBinnerConfig")

        return SpikeBinner(
            bin_size_ms=proto.bin_size_ms,
        )
