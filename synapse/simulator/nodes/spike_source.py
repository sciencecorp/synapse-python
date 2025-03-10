import asyncio
from enum import Enum
import random
import time
import numpy as np

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_source_pb2 import SpikeSourceConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import SpiketrainData

def r_sample(bit_width: int):
    return random.randint(0, 2**bit_width - 1)

class SpikeGenerationMode(Enum):
    kNoise = 0
    kSine = 1
    kLinear = 2

def generate_sine_wave_spikes(
    num_channels: int,
    phase: int,
    base_spike_count: int,
    spike_amplitude: int,
    wave_period: int
) -> np.ndarray:
    """Generate spike counts forming a sine wave pattern across channels.
    """
    y = np.sin(2 * np.pi * phase / wave_period)
    active_channel = int((y + 1) * (num_channels - 1) / 2)
    
    spike_counts = np.full(num_channels, base_spike_count)
    for ch in range(max(0, active_channel - 1), min(num_channels, active_channel + 2)):
        distance = abs(ch - active_channel)
        if distance == 0:
            spike_counts[ch] = base_spike_count + spike_amplitude
        else:
            spike_counts[ch] = base_spike_count + spike_amplitude // 2
    
    return spike_counts

def generate_gradient_spikes(
    num_channels: int,
    phase: int,
    max_spikes: int,
    period: int
) -> np.ndarray:
    """Generate spike counts forming a diagonal gradient pattern across channels.
    """
    spike_counts = np.zeros(num_channels)
    for ch in range(num_channels):
        ch_phase = (phase + ch * period // num_channels) % period
        spike_counts[ch] = max_spikes * ch_phase / period
    return spike_counts.astype(int)

class SpikeSource(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeSource)
        self.__config: SpikeSourceConfig = None
        self.__phase = 0

    def config(self):
        c = super().config()
        if self.__config:
            c.spike_source.CopyFrom(self.__config)
        return c

    def configure(
        self, config: SpikeSourceConfig = SpikeSourceConfig()
    ) -> Status:
        self.__config = config
        return Status()

    async def run(self):
        mode = SpikeGenerationMode.kSine

        if not self.__config:
            self.logger.error("node not configured")
            return

        c = self.__config

        if not c.HasField("electrodes") or not c.electrodes:
            self.logger.error("node not configured with electrodes")
            return
        
        e = c.electrodes
        if not e.channels:
            self.logger.error("node not configured with electrode channels")
            return

        channels = e.channels
        spike_window_ms = c.spike_window_ms if c.spike_window_ms else 20.0

        max_spikes = int(spike_window_ms)
        base_spike_count = max_spikes // 4
        spike_amplitude = max_spikes // 2
        
        num_channels = len(channels)
        wave_period = num_channels * 2

        try:
            t0 = time.time_ns()
            while self.running:
                now = time.time_ns()

                if mode == SpikeGenerationMode.kSine:
                    spike_counts = generate_sine_wave_spikes(
                        num_channels=num_channels,
                        phase=self.__phase,
                        base_spike_count=base_spike_count,
                        spike_amplitude=spike_amplitude,
                        wave_period=wave_period
                    )
                elif mode == SpikeGenerationMode.kLinear:
                    spike_counts = generate_gradient_spikes(
                        num_channels=num_channels,
                        phase=self.__phase,
                        max_spikes=max_spikes,
                        period=wave_period
                    )
                else:
                    spike_counts = np.array([
                        r_sample(4) if random.random() < 0.3 else 0 
                        for _ in range(num_channels)
                    ])
                
                data = SpiketrainData(
                    t0=t0,
                    bin_size_ms=spike_window_ms,
                    spike_counts=spike_counts.tolist()
                )
                
                await self.emit_data(data)

                self.__phase = (self.__phase + 1) % wave_period
                t0 = now

                await asyncio.sleep(spike_window_ms / 1000)
        except Exception as e:
            self.logger.error(f"Error in SpikeSource: {e}")
            raise e
