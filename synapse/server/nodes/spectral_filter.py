from collections import defaultdict
import numpy as np
import queue
from scipy import signal
import threading

from synapse.server.nodes import BaseNode
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spectral_filter_pb2 import (
    SpectralFilterConfig,
    SpectralFilterMethod,
)
from synapse.server.status import Status


def get_filter_coefficients(method, low_cutoff_hz, high_cutoff_hz, sample_rate):
    nyquist = 0.5 * sample_rate
    low = low_cutoff_hz / nyquist
    high = high_cutoff_hz / nyquist
    filter_order = 4

    if method == SpectralFilterMethod.kLowPass:
        return signal.butter(filter_order, high, btype="low")
    elif method == SpectralFilterMethod.kHighPass:
        return signal.butter(filter_order, low, btype="high")
    elif method == SpectralFilterMethod.kBandPass:
        return signal.butter(filter_order, [low, high], btype="band")
    elif method == SpectralFilterMethod.kBandStop:
        return signal.butter(filter_order, [low, high], btype="stop")
    else:
        raise ValueError(f"Unknown filter method: {method}")


class SpectralFilter(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpectralFilter)
        self.__stop_event = threading.Event()
        self.__data_queue = queue.Queue()
        self.sample_rate = None
        self.channel_states = defaultdict(lambda: None)

    def configure(self, config=SpectralFilterConfig()):
        self.method = config.method
        self.low_cutoff_hz = config.low_cutoff_hz
        self.high_cutoff_hz = config.high_cutoff_hz
        return Status()

    def start(self):
        self.logger.info("starting...")
        self.thread = threading.Thread(target=self.run)
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
        if data is None or len(data) < 4:
            self.logger.warning("Received invalid data")
            return

        data_type, t0, sample_data, sample_rate = data

        if data_type != DataType.kBroadband:
            self.logger.warning("Received non-broadband data")
            return

        if sample_rate != self.sample_rate:
            self.b, self.a = get_filter_coefficients(
                self.method, self.low_cutoff_hz, self.high_cutoff_hz, sample_rate
            )
            self.sample_rate = sample_rate
            self.channel_states.clear()

        self.__data_queue.put(data)

    def apply_filter(self, channel_id, samples):
        if self.channel_states[channel_id] is None:
            zi = signal.lfilter_zi(self.b, self.a)
            self.channel_states[channel_id] = zi * samples[0]

        filtered, self.channel_states[channel_id] = signal.lfilter(
            self.b, self.a, samples, zi=self.channel_states[channel_id]
        )
        return filtered

    def run(self):
        while not self.__stop_event.is_set():
            try:
                data = self.__data_queue.get(timeout=1)
            except queue.Empty:
                continue

            data_type, t0, sample_data, sample_rate = data

            filtered_sample_data = []
            for channel_id, samples in sample_data:
                filtered_samples = self.apply_filter(channel_id, np.array(samples))
                filtered_sample_data.append(
                    [channel_id, [int(sample) for sample in filtered_samples]]
                )

            self.emit_data((DataType.kBroadband, t0, filtered_sample_data, sample_rate))
