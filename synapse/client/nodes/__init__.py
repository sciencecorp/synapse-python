from synapse.client.nodes.electrical_broadband import ElectricalBroadband
from synapse.client.nodes.electrical_stimulation import ElectricalStimulation
from synapse.client.nodes.optical_broadband import OpticalBroadband
from synapse.client.nodes.optical_stimulation import OpticalStimulation
from synapse.client.nodes.spectral_filter import SpectralFilter
from synapse.client.nodes.spike_detect import SpikeDetect
from synapse.client.nodes.stream_in import StreamIn
from synapse.client.nodes.stream_out import StreamOut

from synapse.api.node_pb2 import NodeType

NODE_TYPE_OBJECT_MAP = {
    NodeType.kElectricalBroadband: ElectricalBroadband,
    NodeType.kElectricalStimulation: ElectricalStimulation,
    NodeType.kOpticalBroadband: OpticalBroadband,
    NodeType.kOpticalStimulation: OpticalStimulation,
    NodeType.kSpectralFilter: SpectralFilter,
    NodeType.kSpikeDetect: SpikeDetect,
    NodeType.kStreamIn: StreamIn,
    NodeType.kStreamOut: StreamOut,
}
