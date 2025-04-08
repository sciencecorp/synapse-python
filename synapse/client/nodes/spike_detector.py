from typing import Optional, List, Union
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.spike_detect_pb2 import SpikeDetectConfig
from synapse.client.node import Node
from dataclasses import dataclass

@dataclass
class ThresholderConfig:
    threshold_uV: int

@dataclass
class TemplateMatcherConfig:
    template_uV: List[int]

SpikeDetectorConfig = Union[ThresholderConfig, TemplateMatcherConfig]

class SpikeDetector(Node):
    type = NodeType.kSpikeDetector

    def __init__(
        self,
        config: SpikeDetectorConfig,
    ):
        if isinstance(config, ThresholderConfig):
            self.threshold_uV = config.threshold_uV
            self.template_uV = []
        elif isinstance(config, TemplateMatcherConfig):
            self.threshold_uV = None
            self.template_uV = config.template_uV
        else:
            raise ValueError("invalid configuration type provided - must be ThresholderConfig or TemplateMatcherConfig")

    def _to_proto(self):
        n = NodeConfig()
        p = SpikeDetectConfig(
            mode=self.mode,
            threshold_uV=self.threshold_uV,
            template_uV=self.template_uV,
        )
        n.spike_detect.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[SpikeDetectConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, SpikeDetectConfig):
            raise ValueError("proto is not of type SpikeDetectConfig")

        return SpikeDetector(
            mode=proto.mode,
            threshold_uV=proto.threshold_uV,
            template_uV=list(proto.template_uV),
        )
