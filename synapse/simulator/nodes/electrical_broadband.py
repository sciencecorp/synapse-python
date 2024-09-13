from dataclasses import dataclass
import math
import random
import threading
import time
from typing import List
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.electrical_broadband_pb2 import ElectricalBroadbandConfig
from synapse.api.datatype_pb2 import DataType


def r_sample(bit_width: int):
    return random.randint(0, 2 ** bit_width - 1)

@dataclass
class ChannelData:
    channel_id: int
    channel_data: List[int]

@dataclass
class ElectricalBroadbandData:
    bit_width: int
    t0: int
    channel_data: List[ChannelData]

class ElectricalBroadband(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kElectricalBroadband)
        self.stop_event = threading.Event()
        self.__config: ElectricalBroadbandConfig = None
        
    def config(self):
        c = super().config()
        if self.__config:
            c.electrical_broadband.CopyFrom(self.__config)
        return c
   
    def configure(self, config: ElectricalBroadbandConfig = ElectricalBroadbandConfig()) -> Status:
        self.__config = config
        return Status()

    def start(self):
        self.logger.debug("starting...")
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.debug("started")

    def stop(self):
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return
        self.logger.debug("stopping...")
        self.stop_event.set()
        self.thread.join()
        self.logger.debug("stopped")

    def run(self):
        if not self.__config:
            self.logger.error("node not configured")
            return
        
        c = self.__config

        bit_width = c.bit_width if c.bit_width else 4
        channels = c.channels if c.channels else []
        sample_rate = c.sample_rate if c.sample_rate else 16000
        data_type = DataType.kBroadband

        self.logger.info(f" - bit_width: {bit_width} ({math.ceil(bit_width / 8)} bytes, { 2 ** bit_width - 1} max)")
        self.logger.info(f" - sample_rate: {sample_rate}")

        t0 = time.time_ns() // 1000
        while not self.stop_event.is_set():
            now = time.time_ns() // 1000
            elapsed =  now -t0
            n_samples = int(sample_rate * elapsed / 1e6)

            data = ElectricalBroadbandData(
                bit_width=bit_width,
                t0=t0,
                channel_data=[]
            )
            for ch in channels:
                ch_data = [r_sample(bit_width) for _ in range(n_samples)]
                data.channel_data.append(
                    ChannelData(
                        channel_id=ch.id,
                        channel_data=ch_data
                    )
                )

            self.emit_data((data_type, data))

            t0 = now

            time.sleep(0.100)
