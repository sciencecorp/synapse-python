import asyncio
import random
import time

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.spike_source_pb2 import SpikeSourceConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import SpiketrainData

def r_sample(bit_width: int):
    return random.randint(0, 2**bit_width - 1)


class SpikeSource(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kSpikeSource)
        self.__config: SpikeSourceConfig = None

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
        if not self.__config:
            self.logger.error("node not configured")
            return

        c = self.__config

        if not c.HasField("signal") or not c.signal:
            self.logger.error("node signal not configured")
            return
        
        if not c.signal.HasField("electrodes") or not c.signal.electrodes:
            self.logger.error("node not configured with electrodes")
            return
        
        e = c.electrodes
        if not e.channels:
            self.logger.error("node not configured with electrode channels")
            return

        channels = e.channels
        spike_window_ms = c.spike_window_ms if c.spike_window_ms else 20.0

        window_s = spike_window_ms / 1000.0
        min_spikes = max(0, int(1 * window_s))
        max_spikes = min(15, int(200 * window_s))

        t0 = time.time_ns()
        while self.running:
            now = time.time_ns()

            spike_counts = [random.randint(min_spikes, max_spikes) for _ in channels]
            data = SpiketrainData(
                t0=t0,
                bin_size_ms=spike_window_ms,
                spike_counts=spike_counts
            )
            
            await self.emit_data(data)

            t0 = now

            await asyncio.sleep(spike_window_ms / 1000)
