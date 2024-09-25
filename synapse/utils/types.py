from dataclasses import dataclass
from typing import ClassVar, List, Union
from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import (
    NDTPHeader,
    NDTPMessage,
    NDTPPayloadBroadband,
    NDTPPayloadSpiketrain,
)


@dataclass
class ElectricalBroadbandData:
    """
    ElectricalBroadbandData is a timestamped list of channels, each with a list of samples of a given bit width.
    """

    data_type: ClassVar[DataType] = DataType.kBroadband

    @dataclass
    class ChannelData:
        channel_id: int
        channel_data: List[int]

    bit_width: int
    signed: bool
    sample_rate: int
    t0: int
    channels: List[ChannelData]

    def pack(self, seq_number: int) -> List[bytes]:
        """
        Pack the data into an NDTPMessage that can be sent via the StreamOut node.
        """

        packets = []
        seq_number_offset = 0

        for c in self.channels:
            packets.append(
                NDTPMessage(
                    header=NDTPHeader(
                        data_type=DataType.kBroadband,
                        timestamp=self.t0,
                        seq_number=seq_number + seq_number_offset,
                    ),
                    payload=NDTPPayloadBroadband(
                        bit_width=self.bit_width,
                        signed=self.signed,
                        sample_rate=self.sample_rate,
                        channels=[
                            NDTPPayloadBroadband.ChannelData(
                                channel_id=c.channel_id,
                                channel_data=c.channel_data,
                            )
                        ],
                    ),
                ).pack()
            )
            seq_number_offset += 1

        return packets

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage) -> "ElectricalBroadbandData":
        return ElectricalBroadbandData(
            t0=msg.header.timestamp,
            bit_width=msg.payload.bit_width,
            signed=msg.payload.signed,
            sample_rate=msg.payload.sample_rate,
            channels=[
                ElectricalBroadbandData.ChannelData(
                    channel_id=c.channel_id,
                    channel_data=c.channel_data,
                )
                for c in msg.payload.channels
            ],
        )

    @staticmethod
    def unpack(data: bytes) -> "ElectricalBroadbandData":
        """
        Unpack the data from an NDTPMessage that was received via the StreamIn node.
        """
        u = NDTPMessage.unpack(data)

        return ElectricalBroadbandData.from_ndtp_message(u)


@dataclass
class SpiketrainData:
    """
    Spiketrain data is a timestamped list of spike counts for each channel.
    """

    data_type: ClassVar[DataType] = DataType.kSpiketrain
    t0: int
    spike_counts: List[int]

    def pack(self, seq_number: int) -> List[bytes]:
        """
        Pack the data into an NDTPMessage that can be sent via the StreamOut node.
        """
        message = NDTPMessage(
            header=NDTPHeader(
                data_type=DataType.kSpiketrain, timestamp=self.t0, seq_number=seq_number
            ),
            payload=NDTPPayloadSpiketrain(
                spike_counts=self.spike_counts,
            ),
        )

        return [message.pack()]

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage) -> "SpiketrainData":
        return SpiketrainData(
            t0=msg.header.timestamp,
            spike_counts=msg.payload.spike_counts,
        )

    @staticmethod
    def unpack(data: bytes) -> "SpiketrainData":
        """
        Unpack the data from an NDTPMessage that was received via the StreamIn node.
        """
        u = NDTPMessage.unpack(data)

        return SpiketrainData.from_ndtp_message(u)


SynapseData = Union[ElectricalBroadbandData, SpiketrainData]
