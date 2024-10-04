import queue
from collections import defaultdict

import numpy as np
from scipy import signal

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spectral_filter_pb2 import (
    SpectralFilterConfig,
    SpectralFilterMethod,
)
from synapse.server.nodes import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import ElectricalBroadbandData, SynapseData


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
        self.__config = None

    def config(self):
        c = super().config()
        if self.__config:
            c.spectral_filter.CopyFrom(self.__config)
        return c

    def configure(self, config=SpectralFilterConfig()):
        self.method = config.method
        self.low_cutoff_hz = config.low_cutoff_hz
        self.high_cutoff_hz = config.high_cutoff_hz
        self.__config = config
        return Status()

    async def on_data_received(self, data: SynapseData):
        if data.data_type != DataType.kBroadband:
            self.logger.warning("Received non-broadband data")
            return

        if data.sample_rate != self.sample_rate:
            self.b, self.a = get_filter_coefficients(
                self.method, self.low_cutoff_hz, self.high_cutoff_hz, data.sample_rate
            )
            self.sample_rate = data.sample_rate
            self.channel_states.clear()

        await super().on_data_received(data)

    def apply_filter(self, sample_data):
        channel_ids, samples = zip(*sample_data)
        samples_array = np.stack(samples)

        if not hasattr(self, "zi"):
            zi = signal.lfilter_zi(self.b, self.a)
            self.zi = np.outer(np.ones(samples_array.shape[0]), zi)

        # Apply the filter to all channels at once
        filtered_samples, self.zi = signal.lfilter(
            self.b, self.a, samples_array, axis=1, zi=self.zi
        )

        result = [
            [channel_id, filtered_samples[i]]
            for i, channel_id in enumerate(channel_ids)
        ]
        return result

    async def run(self):
        while self.running:
            data = await self.data_queue.get()
            filtered_samples = self.apply_filter(data.samples)

            await self.emit_data(
                ElectricalBroadbandData(
                    data.t0, data.bit_width, filtered_samples, data.sample_rate
                )
            )
