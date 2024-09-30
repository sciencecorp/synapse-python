from synapse.api.node_pb2 import NodeType
from synapse.server.entrypoint import ENTRY_DEFAULTS, main as server
from synapse.server.nodes.stream_in import StreamIn
from synapse.server.nodes.stream_out import StreamOut
from synapse.simulator.nodes.electrical_broadband import ElectricalBroadband
from synapse.simulator.nodes.optical_stimulation import OpticalStimulation


SIMULATOR_NODE_OBJECT_MAP = {
  NodeType.kStreamIn: StreamIn,
  NodeType.kStreamOut: StreamOut,
  NodeType.kElectricalBroadband: ElectricalBroadband,
  NodeType.kOpticalStimulation: OpticalStimulation
}

SIMULATOR_PERIPHERALS = []

SIMULATOR_DEFAULTS = ENTRY_DEFAULTS.copy()
SIMULATOR_DEFAULTS["device_serial"] =  "SFI-SIM001"

def main():
  server(SIMULATOR_NODE_OBJECT_MAP, SIMULATOR_PERIPHERALS, ENTRY_DEFAULTS)
