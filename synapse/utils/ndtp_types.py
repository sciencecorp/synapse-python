from typing import Union

import numpy as np

from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import (
    NDTPHeader,
    NDTPMessage,
    NDTPPayloadBroadband,
    NDTPPayloadBroadbandChannelData,
    NDTPPayloadSpiketrain,
)


class ElectricalBroadbandData:
    __slots__ = ["data_type", "t0", "samples", "sample_rate"]

    def __init__(self, t0, samples, sample_rate):
        self.data_type = DataType.kBroadband
        self.t0 = t0
        self.samples = samples
        self.sample_rate = sample_rate

    def pack(self, seq_number):
        packets = []
        seq_number_offset = 0

        for ch_samples in self.samples:
            packets.append(
                NDTPMessage(
                    header=NDTPHeader(
                        data_type=DataType.kBroadband,
                        timestamp=self.t0,
                        seq_number=seq_number + seq_number_offset,
                    ),
                    payload=NDTPPayloadBroadband(
                        is_signed=True,
                        bit_width=16,
                        sample_rate=self.sample_rate,
                        channels=[
                            NDTPPayloadBroadbandChannelData(
                                channel_id=ch_samples[0], channel_data=ch_samples[1]
                            )
                        ],
                    ),
                ).pack()
            )
            seq_number_offset += 1

        return packets

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage):
        return ElectricalBroadbandData(
            t0=msg.header.timestamp,
            sample_rate=msg.payload.sample_rate,
            samples=[
                (ch.channel_id, np.array(ch.channel_data, dtype=np.int16))
                for ch in msg.payload.channels
            ],
        )

    @staticmethod
    def unpack(data):
        u = NDTPMessage.unpack(data)
        return ElectricalBroadbandData.from_ndtp_message(u)


class SpiketrainData:
    __slots__ = ["data_type", "t0", "spike_counts"]

    def __init__(self, t0, spike_counts):
        self.data_type = DataType.kSpiketrain
        self.t0 = t0
        self.spike_counts = spike_counts

    def pack(self, seq_number):
        message = NDTPMessage(
            header=NDTPHeader(
                data_type=DataType.kSpiketrain,
                timestamp=self.t0,
                seq_number=seq_number,
            ),
            payload=NDTPPayloadSpiketrain(spike_counts=self.spike_counts),
        )

        return [message.pack()]

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage):
        return SpiketrainData(
            t0=msg.header.timestamp,
            spike_counts=msg.payload.spike_counts,
        )

    @staticmethod
    def unpack(data):
        u = NDTPMessage.unpack(data)
        return SpiketrainData.from_ndtp_message(u)


SynapseData = Union[SpiketrainData, ElectricalBroadbandData]
