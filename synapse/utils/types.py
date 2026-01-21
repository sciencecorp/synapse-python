"""
Data types for internal node-to-node communication.

These are simple dataclasses used for passing data between nodes in the
simulator and server. For over-the-wire transmission, data is serialized
to protobuf messages (e.g., BroadbandFrame, SpikeFrame).
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Union

from synapse.api.datatype_pb2 import DataType


@dataclass
class ElectricalBroadbandData:
    """Electrical broadband data from neural electrodes.

    Attributes:
        t0: Timestamp in nanoseconds since epoch.
        bit_width: Bit width of samples (e.g., 12, 16).
        samples: List of (channel_id, samples_list) tuples.
        sample_rate: Sample rate in Hz.
        is_signed: Whether samples are signed integers.
    """
    t0: int = 0
    bit_width: int = 16
    samples: List[Tuple[int, List[int]]] = field(default_factory=list)
    sample_rate: int = 30000
    is_signed: bool = True

    @property
    def data_type(self) -> DataType:
        return DataType.kBroadband


@dataclass
class SpiketrainData:
    """Binned spike train data.

    Attributes:
        t0: Timestamp in nanoseconds since epoch.
        bin_size_ms: Size of each bin in milliseconds.
        spike_counts: List of spike counts per channel.
    """
    t0: int = 0
    bin_size_ms: float = 20.0
    spike_counts: List[int] = field(default_factory=list)

    @property
    def data_type(self) -> DataType:
        return DataType.kSpiketrain


# Union type for all synapse data types
SynapseData = Union[ElectricalBroadbandData, SpiketrainData]
