from collections import defaultdict
from typing import List
import numpy as np
import queue
from scipy import signal

from synapse.server.nodes import BaseNode
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spectral_filter_pb2 import (
    SpectralFilterConfig,
    SpectralFilterMethod,
)
from synapse.server.status import Status
from synapse.utils.types import ElectricalBroadbandData, SynapseData


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
        self.sample_rate = None
        self.channel_states = defaultdict(lambda: None)

    def configure(self, config=SpectralFilterConfig()):
        self.method = config.method
        self.low_cutoff_hz = config.low_cutoff_hz
        self.high_cutoff_hz = config.high_cutoff_hz
        return Status()

    def on_data_received(self, data: SynapseData):
        if data.data_type != DataType.kBroadband:
            self.logger.warning("Received non-broadband data")
            return

        if data.sample_rate != self.sample_rate:
            self.b, self.a = get_filter_coefficients(
                self.method, self.low_cutoff_hz, self.high_cutoff_hz, data.sample_rate
            )
            self.sample_rate = data.sample_rate
            self.channel_states.clear()

        self.data_queue.put(data)

    def apply_filter(self, channels: List[ElectricalBroadbandData.ChannelData]):
        # vectorize channel data so we can apply the filter to all channels at once
        channel_ids = [ch.channel_id for ch in channels]
        samples_array = np.array([ch.channel_data for ch in channels], dtype=np.int16)

        filtered_samples = np.zeros_like(samples_array)
        for i, channel_id in enumerate(channel_ids):
            if self.channel_states[channel_id] is None:
                zi = signal.lfilter_zi(self.b, self.a)
                self.channel_states[channel_id] = zi * samples_array[i, 0]

            filtered_samples[i], self.channel_states[channel_id] = signal.lfilter(
                self.b, self.a, samples_array[i], zi=self.channel_states[channel_id]
            )

        return [
            ElectricalBroadbandData.ChannelData(
                channel_id=channel_id, channel_data=filtered_samples[i].tolist()
            )
            for i, channel_id in enumerate(channel_ids)
        ]

    def run(self):
        while not self.stop_event.is_set():
            try:
                data = self.data_queue.get(timeout=1)
            except queue.Empty:
                continue

            filtered_data = ElectricalBroadbandData(
                bit_width=data.bit_width,
                signed=data.signed,
                sample_rate=data.sample_rate,
                t0=data.t0,
                channels=self.apply_filter(data.channels),
            )

            self.emit_data(filtered_data)
