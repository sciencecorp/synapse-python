from synapse.client.nodes.stream_in import StreamIn
from synapse.client.nodes.stream_out import StreamOut
from synapse.client.nodes.optical_stimulation import OpticalStimulation
from synapse.client.nodes.electrical_broadband import ElectricalBroadband
from synapse.client.nodes.spectral_filter import SpectralFilter
from synapse.client.nodes.spike_detect import SpikeDetect

from synapse.api.node_pb2 import NodeType

NODE_TYPE_OBJECT_MAP = {
    NodeType.kStreamIn: StreamIn,
    NodeType.kStreamOut: StreamOut,
    NodeType.kOpticalStim: OpticalStimulation,
    NodeType.kElectricalBroadband: ElectricalBroadband,
    NodeType.kSpectralFilter: SpectralFilter,
    NodeType.kSpikeDetect: SpikeDetect,
}
