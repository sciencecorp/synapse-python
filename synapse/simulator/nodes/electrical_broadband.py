import asyncio
import random
import time

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp_types import ElectricalBroadbandData

def r_sample(bit_width: int):
    return random.randint(0, 2**bit_width - 1)


class ElectricalBroadband(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kElectricalBroadband)
        self.__config: ElectricalBroadbandConfig = None

    def config(self):
        c = super().config()
        if self.__config:
            c.electrical_broadband.CopyFrom(self.__config)
        return c

    def configure(
        self, config: ElectricalBroadbandConfig = ElectricalBroadbandConfig()
    ) -> Status:
        self.__config = config
        return Status()

    async def run(self):
        if not self.__config:
            self.logger.error("node not configured")
            return

        c = self.__config

        bit_width = c.bit_width if c.bit_width else 4
        channels = c.channels if c.channels else []
        sample_rate = c.sample_rate if c.sample_rate else 16000

        t0 = time.time_ns() // 1000
        while self.running:
            now = time.time_ns() // 1000
            elapsed = now - t0
            n_samples = int(sample_rate * elapsed / 1e6)

            data = ElectricalBroadbandData(
                bit_width=bit_width,
                is_signed=False,
                sample_rate=sample_rate,
                t0=t0,
                samples=[[ch.id, [r_sample(bit_width) for _ in range(n_samples)]] for ch in channels]
            )

            await self.emit_data(data)

            t0 = now

            await asyncio.sleep(0.100)
