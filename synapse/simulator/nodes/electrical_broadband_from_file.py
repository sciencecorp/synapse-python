import asyncio
import json
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import ElectricalBroadbandData


class ElectricalBroadbandFromFile(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kElectricalBroadband)
        self.__config: ElectricalBroadbandConfig = None
        self.__channel_data: Dict[int, List[int]] = {}
        self.__current_idx = 0
        self.sample_rate = 30000
        self.bit_width = 16
        self.data_file = "data/20240916/snuffy_leftpost_20240916-095145.json"
        self.downsample_factor = 2
        self.offset = 15000
        self.__start_time = None
        self.__samples_sent = 0

    def config(self):
        c = super().config()
        if self.__config:
            c.electrical_broadband.CopyFrom(self.__config)
        return c

    def configure(
        self, config: ElectricalBroadbandConfig = ElectricalBroadbandConfig()
    ) -> Status:
        self.sample_rate = config.sample_rate if config.sample_rate else 30000
        self.bit_width = config.bit_width if config.bit_width else 16
        self.sample_rate = self.sample_rate // self.downsample_factor
        self.__config = config
        return Status()

    def _load_data(self, file_path):
        self.__channel_data = {}
        self.logger.info(f"Loading data from {file_path}")
        try:
            with open(file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue  # Skip empty lines
                    _, channel_info = json.loads(line)
                    channel_id, samples = channel_info
                    if channel_id not in self.__channel_data:
                        self.__channel_data[channel_id] = []
                    self.__channel_data[channel_id].extend(samples)
            self.__max_samples = max(
                len(samples) for samples in self.__channel_data.values()
            )
            self.logger.info(
                f"Loaded data for channels: {list(self.__channel_data.keys())}"
            )
            for ch_id, samples in self.__channel_data.items():
                self.logger.info(f"Channel {ch_id} has {len(samples)} samples.")
            self.logger.info(f"Max samples per channel: {self.__max_samples}")
        except Exception as e:
            self.logger.error(f"Error loading data: {e}")
            import traceback

            traceback.print_exc()

    def get_data(self) -> Tuple[Optional[List[Tuple[int, np.ndarray]]], int]:
        if not self.__channel_data:
            self.logger.warning("No channel data available")
            return None, 0

        if self.__start_time is None:
            self.__start_time = int(
                time.time() * 1e6
            )  # Initialize start time on first call

        self.logger.debug(
            f"Current index: {self.__current_idx}, Max samples: {self.__max_samples}"
        )
        # Check if we have enough samples remaining
        samples_remaining = self.__max_samples - self.__current_idx
        if samples_remaining <= 0:
            self.logger.info("End of data reached")
            return None, 0

        # Determine how many samples to collect (up to 3000)
        samples_to_collect = min(3000, samples_remaining)
        samples_to_collect = (
            samples_to_collect // self.downsample_factor
        ) * self.downsample_factor

        data_samples = []
        t0 = int(time.time() * 1e6)  # Current time in microseconds

        for channel_id, samples in self.__channel_data.items():
            # Get a slice of samples for this channel
            if self.__current_idx + samples_to_collect <= len(samples):
                sample_values = samples[
                    self.__current_idx : self.__current_idx + samples_to_collect
                ]
            else:
                # If we don't have enough samples, pad with zeros
                available_samples = len(samples) - self.__current_idx
                sample_values = samples[self.__current_idx :] + [0] * (
                    samples_to_collect - available_samples
                )

            # Convert to numpy array, shift to unsigned, and downsample
            sample_array = np.array(sample_values, dtype=np.int16)
            sample_array = sample_array + self.offset  # Shift the data
            sample_array = sample_array.astype(np.uint16)  # Convert to unsigned
            downsampled_array = sample_array[:: self.downsample_factor]
            data_samples.append((channel_id, downsampled_array))

        self.logger.debug(
            f"Emitting {len(downsampled_array)} downsampled samples (from {samples_to_collect} original samples) at index {self.__current_idx}"
        )
        self.__current_idx += samples_to_collect

        # Calculate timestamp based on samples sent and sample rate
        # Convert to microseconds (hence * 1e6)
        t0 = self.__start_time + int((self.__samples_sent / self.sample_rate) * 1e6)

        # Update samples sent counter (use downsampled count since that's our actual rate)
        self.__samples_sent += len(downsampled_array)

        return data_samples, t0

    async def run(self):
        if not self.__config:
            self.logger.error("Node not configured")
            return

        self._load_data(self.data_file)
        self.__start_time = None  # Reset start time
        self.__samples_sent = 0  # Reset samples counter

        try:
            while self.running:
                data_samples, t0 = self.get_data()
                if data_samples is None:
                    self.__current_idx = 0
                    self.__samples_sent = 0  # Reset counter when we loop
                    self.__start_time = int(time.time() * 1e6)  # Reset start time
                    self.logger.info("Resetting index to 0 and continuing")
                    continue

                # Create ElectricalBroadbandData instance with is_signed=False
                eb_data = ElectricalBroadbandData(
                    t0=t0,
                    bit_width=self.bit_width,
                    samples=data_samples,
                    sample_rate=self.sample_rate * (1.0 / self.downsample_factor),
                    is_signed=False,
                )

                await self.emit_data(eb_data)
                await asyncio.sleep(0.01)
        except Exception as e:
            self.logger.error(f"Error in run loop: {e}")
            import traceback

            traceback.print_exc()