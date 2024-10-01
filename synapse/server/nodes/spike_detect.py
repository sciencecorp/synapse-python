import queue
from collections import defaultdict

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_detect_pb2 import SpikeDetectConfig
from synapse.server.nodes import BaseNode
from synapse.server.status import Status, StatusCode
from synapse.utils.ndtp_types import SpiketrainData

REFRACTORY_PERIOD_S = 0.001


class SpikeDetect(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeDetect)
        self.samples_since_last_spike = defaultdict(lambda: 0)
        self.channel_buffers = defaultdict(list)
        self.__config = None

    def config(self):
        c = super().config()
        if self.__config:
            c.spike_detect.CopyFrom(self.__config)
        return c

    def configure(self, config=SpikeDetectConfig()):
        self.mode = config.mode
        self.threshold_uV = config.threshold_uV
        self.template_uV = config.template_uV
        self.sort = config.sort
        self.bin_size_ms = config.bin_size_ms

        if self.mode == SpikeDetectConfig.SpikeDetectMode.kThreshold:
            if self.threshold_uV == 0:
                self.logger.warning("Threshold mode selected but threshold_uV is 0")
        elif self.mode == SpikeDetectConfig.SpikeDetectMode.kTemplate:
            return Status(
                StatusCode.kUnimplemented, "Template mode is not yet implemented"
            )
        elif self.mode == SpikeDetectConfig.SpikeDetectConfig.SpikeDetectMode.kWavelet:
            return Status(
                StatusCode.kUnimplemented, "Wavelet mode is not yet implemented"
            )
        else:
            return Status(
                StatusCode.kInvalidConfiguration,
                f"Unknown spike detection mode: {self.mode}",
            )

        self.__config = config
        return Status()

    async def run(self):
        while not self.stop_event.is_set():
            try:
                data = self.data_queue.get(timeout=1)
            except queue.Empty:
                continue

            if data.data_type != DataType.kBroadband:
                self.logger.warning("Received non-broadband data")
                continue

            for channel_id, samples in data.samples:
                self.channel_buffers[channel_id].extend(samples)

            refractory_period_in_samples = int(REFRACTORY_PERIOD_S * data.sample_rate)
            bin_size_in_samples = int(self.bin_size_ms * data.sample_rate / 1000)

            while any(
                len(buffer) >= bin_size_in_samples
                for buffer in self.channel_buffers.values()
            ):
                spike_counts = []
                for channel_id, buffer in self.channel_buffers.items():
                    spike_count = 0
                    if len(buffer) >= bin_size_in_samples:
                        # pop a bin's worth of samples off the buffer
                        self.channel_buffers[channel_id] = buffer[bin_size_in_samples:]
                        bin_samples = buffer[:bin_size_in_samples]

                        for sample in bin_samples:
                            threshold_crossed = abs(sample) > self.threshold_uV
                            since_spike = self.samples_since_last_spike[channel_id]
                            recovered = since_spike > refractory_period_in_samples

                            if threshold_crossed and recovered:
                                spike_count += 1
                                self.samples_since_last_spike[channel_id] = 0
                            else:
                                self.samples_since_last_spike[channel_id] += 1

                    spike_counts.append(spike_count)

                await self.emit_data(
                    SpiketrainData(t0=data.t0, spike_counts=spike_counts)
                )
