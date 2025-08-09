from synapse.api.node_pb2 import NodeType
from synapse.server.entrypoint import ENTRY_DEFAULTS, main as server
from synapse.simulator.nodes.broadband_source import BroadbandSource
from synapse.simulator.nodes.optical_stimulation import OpticalStimulation
from synapse.simulator.nodes.spike_source import SpikeSource
from synapse.server.nodes.spectral_filter import SpectralFilter

SIMULATOR_NODE_OBJECT_MAP = {
    NodeType.kBroadbandSource: BroadbandSource,
    NodeType.kSpectralFilter: SpectralFilter,
    NodeType.kSpikeSource: SpikeSource,
    NodeType.kOpticalStimulation: OpticalStimulation,
}

SIMULATOR_PERIPHERALS = []

SIMULATOR_DEFAULTS = ENTRY_DEFAULTS.copy()
SIMULATOR_DEFAULTS["device_serial"] = "SFI-SIM001"


def main():
    server(SIMULATOR_NODE_OBJECT_MAP, SIMULATOR_PERIPHERALS, ENTRY_DEFAULTS)
