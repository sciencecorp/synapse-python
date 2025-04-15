import queue
from collections import defaultdict

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_detector_pb2 import SpikeDetectorConfig
from synapse.server.nodes import BaseNode
from synapse.server.status import Status, StatusCode
from synapse.utils.ndtp_types import SpiketrainData


from enum import Enum

class DetectorMode(Enum):
    UNKNOWN = 0
    THRESHOLD = 1
    TEMPLATE = 2

class SpikeDetector(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeDetector)
        self.__config = None

        self.samples_per_spike = None
        self.threshold_uV = None
        self.template_uV = None
        self.mode = DetectorMode.UNKNOWN

    def config(self):
        c = super().config()

        c.spike_detector.samples_per_spike = self.samples_per_spike
        
        if self.mode == DetectorMode.THRESHOLD:
            c.spike_detector.thresholder.threshold_uV = self.threshold_uV
        elif self.mode == DetectorMode.TEMPLATE:
            c.spike_detector.template_matcher.template_uV.extend(self.template_uV)
            
        return c

    def configure(self, config: SpikeDetectorConfig):
        self.samples_per_spike = config.samples_per_spike
    
        if config.HasField('thresholder'):
            self.mode = DetectorMode.THRESHOLD
            self.threshold_uV = config.thresholder.threshold_uV
            self.template_uV = []

            if self.threshold_uV == 0:
                self.logger.warning(f"threshold mode selected but threshold_uV is 0")
        elif config.HasField('template_matcher'):
            return Status(
                StatusCode.kUnimplemented, "template matcher not implemented"
            )

        else:
            return Status(
                StatusCode.kInvalidConfiguration,
                "config must contain either 'thresholder' or 'template_matcher'"
            )

        return Status()

    async def run(self):
        while self.running:
            data = await self.data_queue.get()

            if data.data_type != DataType.kBroadband:
                self.logger.warning("received non-broadband data")
                continue

                # await self.emit_data(
                #     SpiketrainData(t0=data.t0, bin_size_ms=self.bin_size_ms, spike_counts=spike_counts)
                # )
