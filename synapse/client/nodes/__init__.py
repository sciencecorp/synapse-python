from synapse.client.nodes.broadband_source import BroadbandSource
from synapse.client.nodes.electrical_stimulation import ElectricalStimulation
from synapse.client.nodes.optical_stimulation import OpticalStimulation
from synapse.client.nodes.spectral_filter import SpectralFilter
from synapse.client.nodes.spike_detect import SpikeDetect
from synapse.client.nodes.spike_source import SpikeSource
from synapse.client.nodes.stream_in import StreamIn
from synapse.client.nodes.stream_out import StreamOut

from synapse.api.node_pb2 import NodeType

NODE_TYPE_OBJECT_MAP = {
    NodeType.kBroadbandSource: BroadbandSource,
    NodeType.kElectricalStimulation: ElectricalStimulation,
    NodeType.kOpticalStimulation: OpticalStimulation,
    NodeType.kSpectralFilter: SpectralFilter,
    NodeType.kSpikeDetect: SpikeDetect,
    NodeType.kSpikeSource: SpikeSource,
    NodeType.kStreamIn: StreamIn,
    NodeType.kStreamOut: StreamOut,
}
