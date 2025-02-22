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

def chunk_channel_data(bit_width: int, ch_data: List[float], max_payload_size_bytes: int):
    n_packets = math.ceil(len(ch_data) * bit_width / (max_payload_size_bytes * 8))
    n_pts_per_packet = math.ceil(len(ch_data) / n_packets)

    for i in range(n_packets):
        start_idx = i * n_pts_per_packet
        end_idx = min(start_idx + n_pts_per_packet, len(ch_data))
        yield ch_data[start_idx:end_idx]

class ElectricalBroadbandData:
    """Electrical broadband data from neural recordings.

    Attributes:
        t0 (int): Start timestamp in nanoseconds
        is_signed (bool): Whether the data is represented using signed integers
        bit_width (int): Number of bits used to represent each sample
        samples (Tuple[int, List[float]]): Tuple of (channel_id, data_samples)
        sample_rate (float): Sample rate in Hz
    """
    __slots__ = ["data_type", "t0", "is_signed", "bit_width", "samples", "sample_rate"]

    def __init__(self, t0, bit_width, samples: Tuple[int, List[float]], sample_rate, is_signed=True):
        self.data_type = DataType.kBroadband

        self.t0 = t0 # ns
        self.is_signed = is_signed
        self.bit_width = bit_width
        self.samples = samples
        self.sample_rate = sample_rate

    def pack(self, seq_number: int) -> Tuple[List[bytes], int]:
        packets = []
        seq = seq_number

        try: 
            for ch_samples in self.samples:
                ch_id = ch_samples[0]
                ch_data = ch_samples[1]
                if (len(ch_data) == 0):
                    continue

                n_samples = 0

                for ch_sample_sub in chunk_channel_data(self.bit_width, ch_data, MAX_CH_PAYLOAD_SIZE_BYTES):
                    t_offset = round(n_samples * 1e6 / self.sample_rate)
                    timestamp = self.t0 + t_offset
                    msg = NDTPMessage(
                        header=NDTPHeader(
                            data_type=DataType.kBroadband,
                            timestamp=timestamp,
                            seq_number=seq,
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
                    n_samples += len(ch_sample_sub)
                    packed = msg.pack()
                    packets.append(packed)
                    seq = (seq + 1) % 2**16
        except Exception as e:
            print(f"Error packing NDTP message: {e}")

        return packets, seq

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
    """Binned spike train data from neural recordings.

    Attributes:
        t0 (int): Start timestamp in nanoseconds
        bin_size_ms (float): Size of each time bin in milliseconds
        spike_counts (List[int]): Number of spikes in each time bin
    """
    __slots__ = ["data_type", "t0", "bin_size_ms", "spike_counts"]

    def __init__(self, t0, bin_size_ms, spike_counts):
        self.data_type = DataType.kSpiketrain
        self.t0 = t0 # ns
        self.bin_size_ms = bin_size_ms
        self.spike_counts = spike_counts

    def pack(self, seq_number: int):
        message = NDTPMessage(
            header=NDTPHeader(
                data_type=DataType.kSpiketrain,
                timestamp=self.t0,
                seq_number=seq_number,
            ),
            payload=NDTPPayloadSpiketrain(
                bin_size_ms=self.bin_size_ms,
                spike_counts=self.spike_counts
            ),
        )
        seq_number = (seq_number + 1) % 2**16
        return [message.pack()], seq_number

    @staticmethod
    def from_ndtp_message(msg: NDTPMessage):
        return SpiketrainData(
            t0=msg.header.timestamp,
            bin_size_ms=msg.payload.bin_size_ms,
            spike_counts=msg.payload.spike_counts,
        )

    @staticmethod
    def unpack(data):
        u = NDTPMessage.unpack(data)
        return SpiketrainData.from_ndtp_message(u)

    def to_list(self):
        return [self.t0, self.bin_size_ms, list(self.spike_counts)]


SynapseData = Union[SpiketrainData, ElectricalBroadbandData]
