import numpy as np
import queue
import threading
from collections import defaultdict

from synapse.server.nodes import BaseNode
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_detect_pb2 import SpikeDetectConfig, SpikeDetectOptions
from synapse.server.status import Status

REFRACTORY_PERIOD_S = 0.001


class SpikeDetect(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeDetect)
        self.__stop_event = threading.Event()
        self.__data_queue = queue.Queue()
        self.samples_since_last_spike = defaultdict(lambda: 0)
        self.channel_buffers = defaultdict(list)

    def configure(self, config=SpikeDetectConfig()):
        self.mode = config.mode
        self.threshold_uV = config.threshold_uV
        self.template_uV = config.template_uV
        self.sort = config.sort
        self.bin_size_ms = config.bin_size_ms

        if self.mode == SpikeDetectOptions.SpikeDetectMode.kThreshold:
            if self.threshold_uV == 0:
                self.logger.warning("Threshold mode selected but threshold_uV is 0")
        elif self.mode == SpikeDetectOptions.SpikeDetectMode.kTemplate:
            raise NotImplementedError("Template mode is not yet implemented")
        elif self.mode == SpikeDetectConfig.SpikeDetectOptions.SpikeDetectMode.kWavelet:
            raise NotImplementedError("Wavelet mode is not yet implemented")
        else:
            raise ValueError(f"Unknown spike detection mode: {self.mode}")
        return Status()

    def start(self):
        self.logger.info("starting...")
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.info("started")
        return Status()

    def stop(self):
        self.logger.info("stopping...")
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return

        self.__stop_event.set()
        self.thread.join()
        self.logger.info("stopped")
        return Status()

    def on_data_received(self, data):
        self.__data_queue.put(data)

    def run(self):
        while not self.__stop_event.is_set():
            try:
                data = self.__data_queue.get(timeout=1)
            except queue.Empty:
                continue

            if data is None or len(data) < 4:
                self.logger.warning("Received invalid data")
                continue

            data_type, t0, sample_data, sample_rate = data
            if data_type != DataType.kBroadband:
                self.logger.warning("Received non-broadband data")
                continue

            for channel_id, samples in sample_data:
                self.channel_buffers[channel_id].extend(samples)

            refractory_period_in_samples = int(REFRACTORY_PERIOD_S * sample_rate)
            bin_size_in_samples = int(self.bin_size_ms * sample_rate / 1000)

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

                self.emit_data((DataType.kSpiketrain, t0, spike_counts))
