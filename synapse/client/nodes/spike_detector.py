from typing import Optional, List, Union, Tuple
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.spike_detector_pb2 import SpikeDetectorConfig
from synapse.client.node import Node
from dataclasses import dataclass

@dataclass
class ThresholderConfig:
    threshold_uV: int

@dataclass
class TemplateMatcherConfig:
    template_uV: List[int]

class SpikeDetector(Node):
    type = NodeType.kSpikeDetector

    samples_per_spike: int
    threshold_uV: Optional[int]
    template_uV: Optional[List[int]]

    def __init__(
        self,
        samples_per_spike: int,
        config: Union[ThresholderConfig, TemplateMatcherConfig],
    ):
        self.samples_per_spike = samples_per_spike

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
        p = SpikeDetectorConfig()

        
        if self.threshold_uV is not None:
            p.thresholder.threshold_uV = self.threshold_uV
        elif self.template_uV:
            p.template_matcher.template_uV.extend(self.template_uV)
        p.samples_per_spike = self.samples_per_spike
            
        n.spike_detector.CopyFrom(p)
        
        return n

    @staticmethod
    def _from_proto(proto: Optional[SpikeDetectorConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, SpikeDetectorConfig):
            raise ValueError("proto is not of type SpikeDetectorConfig")

        samples_per_spike = proto.samples_per_spike

        config: Tuple[ThresholderConfig, TemplateMatcherConfig] = None
        # Parse the mode from the oneof
        if proto.HasField('thresholder'):
            config = ThresholderConfig(threshold_uV=proto.thresholder.threshold_uV)
        elif proto.HasField('template_matcher'):
            config = TemplateMatcherConfig(template_uV=list(proto.template_matcher.template_uV))
        else:
            raise ValueError("Invalid configuration: must contain either 'thresholder' or 'template_matcher'")

        return SpikeDetector(samples_per_spike=samples_per_spike, config=config)
