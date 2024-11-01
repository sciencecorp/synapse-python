from collections import defaultdict

import numpy as np
from scipy.signal import find_peaks

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_detect_pb2 import SpikeDetectConfig
from synapse.server.nodes import BaseNode
from synapse.server.status import Status, StatusCode
from synapse.utils.ndtp_types import SpiketrainData


class SpikeDetect(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeDetect)
        self.channel_buffers = defaultdict(list)
        self.buffer_start_ts = None
        self.__config = None

        self.upper_threshold_uV = 200.0
        self.min_spike_width_ms = 0.2
        self.max_spike_width_ms = 0.4
        self.refractory_period_ms = 1.0

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
        elif self.mode == SpikeDetectConfig.SpikeDetectMode.kWavelet:
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
        sample_rate = None
        while self.running:
            data = await self.data_queue.get()

            if data.data_type != DataType.kBroadband:
                self.logger.warning("Received non-broadband data")
                continue

            if self.buffer_start_ts is None:
                self.buffer_start_ts = data.t0

            if sample_rate is None:
                sample_rate = data.sample_rate

                self.bin_size_samples = int(self.bin_size_ms * sample_rate / 1000)
                self.min_width_samples = int(
                    self.min_spike_width_ms * sample_rate / 1000
                )
                self.max_width_samples = int(
                    self.max_spike_width_ms * sample_rate / 1000
                )
                self.refractory_period_samples = int(
                    self.refractory_period_ms * sample_rate / 1000
                )
                self.overlap_samples = self.max_width_samples
                self.bin_duration_us = self.bin_size_samples * 1e6 / sample_rate

            for channel_id, samples in data.samples:
                self.channel_buffers[channel_id].extend(samples)

            # Check if all channels have enough data to process
            min_buffer_length = min(
                len(buffer) for buffer in self.channel_buffers.values()
            )

            while min_buffer_length >= self.bin_size_samples + self.overlap_samples:
                window_data = []
                channel_ids = sorted(self.channel_buffers.keys())
                for channel_id in channel_ids:
                    buffer = self.channel_buffers[channel_id]
                    processing_samples = buffer[
                        : self.bin_size_samples + self.overlap_samples
                    ]
                    window_data.append(processing_samples)
                window_data = np.array(window_data)
                # Invert signal for negative peaks
                signal_data = -np.array(window_data)

                spike_counts = []
                for idx, channel_id in enumerate(channel_ids):
                    channel_signal = signal_data[idx]

                    peaks, properties = find_peaks(
                        channel_signal,
                        height=self.threshold_uV,
                        prominence=self.threshold_uV,
                        width=(self.min_width_samples, self.max_width_samples),
                        distance=self.refractory_period_samples,
                    )

                    # Only consider peaks that start within the current bin (exclude overlap)
                    peaks_in_bin = peaks[peaks < self.bin_size_samples]
                    heights_in_bin = properties["peak_heights"][
                        peaks < self.bin_size_samples
                    ]

                    # Exclude peaks exceeding the upper threshold
                    valid_peaks = heights_in_bin <= self.upper_threshold_uV
                    peaks_in_bin = peaks_in_bin[valid_peaks]

                    spike_count = len(peaks_in_bin)
                    spike_counts.append(spike_count)

                await self.emit_data(
                    SpiketrainData(
                        t0=self.buffer_start_ts,
                        bin_size_ms=self.bin_size_ms,
                        spike_counts=spike_counts,
                    )
                )

                # Advance the timestamp for the next bin
                self.buffer_start_ts += self.bin_duration_us

                # Update buffers by removing the processed bin (excluding the overlap)
                for channel_id in self.channel_buffers:
                    buffer = self.channel_buffers[channel_id]
                    # Keep overlap_samples for next bin
                    self.channel_buffers[channel_id] = buffer[self.bin_size_samples :]

                # Update min_buffer_length for the next iteration
                min_buffer_length = min(
                    len(buffer) for buffer in self.channel_buffers.values()
                )
