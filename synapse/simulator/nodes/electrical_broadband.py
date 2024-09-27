import random
import time
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.types import ElectricalBroadbandData


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

    def run(self):
        if not self.__config:
            self.logger.error("node not configured")
            return

        c = self.__config

        bit_width = c.bit_width if c.bit_width else 4
        channels = c.channels if c.channels else []
        sample_rate = c.sample_rate if c.sample_rate else 16000

        t0 = time.time_ns() // 1000
        while not self.stop_event.is_set():
            now = time.time_ns() // 1000
            elapsed = now - t0
            n_samples = int(sample_rate * elapsed / 1e6)

            data = ElectricalBroadbandData(
                bit_width=bit_width,
                signed=False,
                sample_rate=sample_rate,
                t0=t0,
                channels=[
                    ElectricalBroadbandData.ChannelData(
                        channel_id=ch.id,
                        channel_data=[r_sample(bit_width) for _ in range(n_samples)],
                    )
                    for ch in channels
                ],
            )

            self.emit_data(data)

            t0 = now

            time.sleep(0.100)
