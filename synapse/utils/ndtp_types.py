import math
from typing import List, Tuple, Union

import numpy as np

from synapse.api.datatype_pb2 import DataType
from synapse.utils.ndtp import (
    NDTPHeader,
    NDTPMessage,
    NDTPPayloadBroadband,
    NDTPPayloadBroadbandChannelData,
    NDTPPayloadSpiketrain,
)

MAX_CH_PAYLOAD_SIZE_BYTES = 1400

def chunk_channel_data(ch_data: List[float], max_payload_size_bytes: int):
    n_packets = math.ceil(len(ch_data) / max_payload_size_bytes)
    n_pts_per_packet = math.ceil(len(ch_data) / n_packets)
    for i in range(n_packets):
        start_idx = i * n_pts_per_packet
        end_idx = min(start_idx + n_pts_per_packet, len(ch_data))
        yield ch_data[start_idx:end_idx]

class ElectricalBroadbandData:
    __slots__ = ["data_type", "t0", "is_signed", "bit_width", "samples", "sample_rate"]

    def __init__(self, t0, bit_width, samples: Tuple[int, List[float]], sample_rate, is_signed=True):
        self.data_type = DataType.kBroadband
        self.t0 = t0
        self.is_signed = is_signed
        self.bit_width = bit_width
        self.samples = samples
        self.sample_rate = sample_rate

    def pack(self, seq_number: int):
        packets = []
        seq_number_offset = 0

        try: 
            for ch_samples in self.samples:
                ch_id = ch_samples[0]
                ch_data = ch_samples[1]
                if (len(ch_data) == 0):
                    continue

                for ch_sample_sub in chunk_channel_data(ch_data, MAX_CH_PAYLOAD_SIZE_BYTES):
                    msg = NDTPMessage(
                        header=NDTPHeader(
                            data_type=DataType.kBroadband,
                            timestamp=self.t0,
                            seq_number=seq_number + seq_number_offset,
                        ),
                        payload=NDTPPayloadBroadband(
                            is_signed=self.is_signed,
                            bit_width=self.bit_width,
                            sample_rate=self.sample_rate,
                            channels=[
                                NDTPPayloadBroadbandChannelData(
                                    channel_id=ch_id, channel_data=ch_sample_sub
                                )
                            ],
                        ),
                    )
                    packed = msg.pack()
                    packets.append(packed)
                    seq_number_offset += 1
        except Exception as e:
            print(f"Error packing NDTP message: {e}")

        return packets

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage):
        dtype = np.int16 if msg.payload.is_signed else np.uint16
        return ElectricalBroadbandData(
            t0=msg.header.timestamp,
            bit_width=msg.payload.bit_width,
            is_signed=msg.payload.is_signed,
            sample_rate=msg.payload.sample_rate,
            samples=[
                (ch.channel_id, np.array(ch.channel_data, dtype=dtype))
                for ch in msg.payload.channels
            ],
        )

    @staticmethod
    def unpack(data):
        u = NDTPMessage.unpack(data)
        return ElectricalBroadbandData.from_ndtp_message(u)

    def to_list(self):
        return [
            self.t0,
            [
                (int(channel_id), samples.tolist())
                for channel_id, samples in self.samples
            ],
        ]


class SpiketrainData:
    __slots__ = ["data_type", "t0", "spike_counts"]

    def __init__(self, t0, spike_counts):
        self.data_type = DataType.kSpiketrain
        self.t0 = t0
        self.spike_counts = spike_counts

    def pack(self, seq_number: int):
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

    def to_list(self):
        return [self.t0, list(self.spike_counts)]


SynapseData = Union[SpiketrainData, ElectricalBroadbandData]
