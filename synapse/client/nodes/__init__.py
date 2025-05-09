from synapse.client.nodes.broadband_source import BroadbandSource
from synapse.client.nodes.electrical_stimulation import ElectricalStimulation
from synapse.client.nodes.optical_stimulation import OpticalStimulation
from synapse.client.nodes.spectral_filter import SpectralFilter
from synapse.client.nodes.spike_binner import SpikeBinner
from synapse.client.nodes.spike_detector import SpikeDetector
from synapse.client.nodes.spike_source import SpikeSource
from synapse.client.nodes.stream_in import StreamIn
from synapse.client.nodes.stream_out import StreamOut
from synapse.client.nodes.disk_writer import DiskWriter
from synapse.client.nodes.application_node import ApplicationNode

from synapse.api.node_pb2 import NodeType

NODE_TYPE_OBJECT_MAP = {
    NodeType.kBroadbandSource: BroadbandSource,
    NodeType.kDiskWriter: DiskWriter,
    NodeType.kElectricalStimulation: ElectricalStimulation,
    NodeType.kOpticalStimulation: OpticalStimulation,
    NodeType.kSpectralFilter: SpectralFilter,
    NodeType.kSpikeBinner: SpikeBinner,
    NodeType.kSpikeDetector: SpikeDetector,
    NodeType.kSpikeSource: SpikeSource,
    NodeType.kStreamIn: StreamIn,
    NodeType.kStreamOut: StreamOut,
    NodeType.kApplication: ApplicationNode,
}
