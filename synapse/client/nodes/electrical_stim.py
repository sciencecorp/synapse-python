from typing import Optional
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.electrical_stim_pb2 import ElectricalStimConfig
from synapse.client.channel import Channel
from synapse.client.node import Node

class ElectricalStimulation(Node):
    type = NodeType.kElectricalStim

    def __init__(
        self,
        peripheral_id,
        channels,
        bit_width,
        sample_rate,
        lsb
    ):
        self.peripheral_id = peripheral_id
        self.channels = channels
        self.bit_width = bit_width
        self.sample_rate = sample_rate
        self.lsb = lsb

    def _to_proto(self):
        channels = [c.to_proto() for c in self.channels]
        n = NodeConfig()
        p = ElectricalStimConfig(
            peripheral_id=self.peripheral_id,
            channels=channels,
            bit_width=self.bit_width,
            sample_rate=self.sample_rate,
            lsb=self.lsb
        )
        n.electrical_stim.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[ElectricalStimConfig]):
        if not proto:
            raise ValueError("parameter 'proto' is missing")
        if not isinstance(proto, ElectricalStimConfig):
            raise ValueError("proto is not of type ElectricalStimConfig")

        channels = [Channel.from_proto(c) for c in proto.channels]
        return ElectricalStimulation(
            peripheral_id=proto.peripheral_id,
            channels=channels,
            bit_width=proto.bit_width,
            sample_rate=proto.sample_rate,
            lsb=proto.lsb
        )
