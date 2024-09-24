from dataclasses import dataclass
from typing import List, Union
from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import NDTPHeader, NDTPMessage, NDTPPayloadBroadband, NDTPPayloadSpiketrain

"""
    ElectricalBroadbandData is a timestamped list of channels, each with a list of samples of a given bit width.
"""
@dataclass
class ElectricalBroadbandData:
    @dataclass
    class ChannelData:
        channel_id: int
        channel_data: List[int]

    bit_width: int
    t0: int
    channels: List

    '''
    Pack the data into an NDTPMessage that can be sent via the StreamOut node.
    '''
    def pack(self, seq_number: int) -> bytes:
        message = NDTPMessage(
            header=NDTPHeader(
                data_type=DataType.kBroadband,
                timestamp=self.t0,
                seq_number=seq_number
            ),
            payload=NDTPPayloadBroadband(
                bit_width=self.bit_width,
                channels=[
                    NDTPPayloadBroadband.ChannelData(
                        channel_id=c.channel_id,
                        channel_data=c.channel_data,
                    )
                    for c in self.channels
                ]
            ),
        )

        return message.pack()

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage) -> 'ElectricalBroadbandData':
        return ElectricalBroadbandData(
            t0=msg.header.timestamp,
            bit_width=msg.payload.bit_width,
            channels=[
                ElectricalBroadbandData.ChannelData(
                    channel_id=c.channel_id,
                    channel_data=c.channel_data,
                )
                for c in msg.payload.channels
            ]
        )

    '''
    Unpack the data from an NDTPMessage that was received via the StreamIn node.
    '''
    @staticmethod
    def unpack(data: bytes) -> 'ElectricalBroadbandData':
        u = NDTPMessage.unpack(data)
        
        return ElectricalBroadbandData.from_ndtp_message(u)

"""
    Spiketrain data is a timestamped list of spike counts for each channel.
"""
@dataclass
class SpiketrainData:
    t0: int
    spike_counts: List[int]

    '''
    Pack the data into an NDTPMessage that can be sent via the StreamOut node.
    '''
    def pack(self, seq_number: int) -> bytes:
        message = NDTPMessage(
            header=NDTPHeader(
                data_type=DataType.kSpiketrain,
                timestamp=self.t0,
                seq_number=seq_number
            ),
            payload=NDTPPayloadSpiketrain(
                spike_counts=self.spike_counts,
            ),
        )

        return message.pack()

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage) -> 'SpiketrainData':
        return SpiketrainData(
            t0=u.header.timestamp,
            spike_counts=u.payload.spike_counts,
        )

    '''
    Unpack the data from an NDTPMessage that was received via the StreamIn node.
    '''
    @staticmethod
    def unpack(data: bytes) -> 'SpiketrainData':
        u = NDTPMessage.unpack(data)

        return SpiketrainData.from_ndtp_message(u)

SynapseData = Union[
    bytes,
    ElectricalBroadbandData,
    SpiketrainData
]
