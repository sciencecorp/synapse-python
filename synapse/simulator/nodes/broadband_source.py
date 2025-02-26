import asyncio
import random
import time

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.broadband_source_pb2 import BroadbandSourceConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import ElectricalBroadbandData

def r_sample(bit_width: int):
    return random.randint(0, 2**bit_width - 1)


class BroadbandSource(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kBroadbandSource)
        self.__config: BroadbandSourceConfig = None

    def config(self):
        c = super().config()
        if self.__config:
            c.broadband_source.CopyFrom(self.__config)
        return c

    def configure(
        self, config: BroadbandSourceConfig = BroadbandSourceConfig()
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
        
        if not c.signal.HasField("electrode") or not c.signal.electrode:
            self.logger.error("node signal electrode not configured")
            return
        
        e = c.signal.electrode
        if not e.channels:
            self.logger.error("node signal electrode channels not configured")
            return

        channels = e.channels
        bit_width = c.bit_width if c.bit_width else 4
        sample_rate_hz = c.sample_rate_hz if c.sample_rate_hz else 16000

        t_last_ns = time.time_ns()
        while self.running:
            await asyncio.sleep(0.01)
            
            now = time.time_ns()
            elapsed_ns = now - t_last_ns
            n_samples = int(sample_rate_hz * elapsed_ns / 1e9)
            
            samples = [[ch.id, [r_sample(bit_width) for _ in range(n_samples)]] for ch in channels]

            data = ElectricalBroadbandData(
                bit_width=bit_width,
                is_signed=False,
                sample_rate=sample_rate_hz,
                t0=t_last_ns,
                samples=samples
            )

            await self.emit_data(data)
            t_last_ns = now
