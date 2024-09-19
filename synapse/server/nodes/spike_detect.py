import numpy as np
import queue
import threading
from collections import defaultdict

from synapse.server.nodes import BaseNode
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_detect_pb2 import SpikeDetectConfig
from synapse.server.status import Status

REFRACTORY_PERIOD_S = 0.001


class SpikeDetect(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeDetect)
        self.stop_event = threading.Event()
        self.__data_queue = queue.Queue()
        self.last_spike_times = defaultdict(lambda: 0)

    def configure(self, config=SpikeDetectConfig()):
        self.mode = config.mode
        self.threshold_uV = config.threshold_uV
        self.template_uV = config.template_uV
        self.sort = config.sort

        if self.mode == SpikeDetectConfig.SpikeDetectOptions.SpikeDetectMode.kThreshold:
            if self.threshold_uV == 0:
                self.logger.warning("Threshold mode selected but threshold_uV is 0")
        elif (
            self.mode == SpikeDetectConfig.SpikeDetectOptions.SpikeDetectMode.kTemplate
        ):
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
        while not self.stop_event.is_set():
            try:
                data = self.__data_queue.get(timeout=1)
            except queue.Empty:
                continue

            if data is None or len(data) < 4:
                self.logger.warning("Received invalid data")
                continue

            data_type, t0, samples, sample_rate = data

            if data_type != DataType.kBroadband:
                self.logger.warning("Received non-broadband data")
                continue

            spike_times = []
            for channel in samples:
                channel_id = channel[0]
                for i, sample in enumerate(channel[1]):
                    sample_time = t0 + i / sample_rate

                    if (
                        np.abs(sample) > self.threshold_uV
                        and sample_time - self.last_spike_times[channel_id]
                        > REFRACTORY_PERIOD_S
                    ):
                        spike_times.append((channel_id, sample_time))
                        self.last_spike_times[channel_id] = sample_time

            self.emit_data((DataType.kSpiketrain, t0, spike_times))
