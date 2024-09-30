from typing import Optional, List
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.spike_detect_pb2 import SpikeDetectConfig
from synapse.client.node import Node


class SpikeDetect(Node):
    type = NodeType.kSpikeDetect

    def __init__(
        self,
        mode: SpikeDetectConfig.SpikeDetectMode,
        threshold_uV: int = None,
        template_uV: List[int] = None,
        sort: bool = False,
        bin_size_ms: int = None,
    ):
        self.mode = mode
        self.threshold_uV = threshold_uV
        self.template_uV = template_uV or []
        self.sort = sort
        self.bin_size_ms = bin_size_ms

    def _to_proto(self):
        n = NodeConfig()
        p = SpikeDetectConfig(
            mode=self.mode,
            threshold_uV=self.threshold_uV,
            template_uV=self.template_uV,
            sort=self.sort,
            bin_size_ms=self.bin_size_ms,
        )
        n.spike_detect.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[SpikeDetectConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, SpikeDetectConfig):
            raise ValueError("proto is not of type SpikeDetectConfig")

        return SpikeDetect(
            mode=proto.mode,
            threshold_uV=proto.threshold_uV,
            template_uV=list(proto.template_uV),
            sort=proto.sort,
            bin_size_ms=proto.bin_size_ms,
        )

    @staticmethod
    def from_proto(proto):
        return SpikeDetect._from_proto(proto.spike_detect)
