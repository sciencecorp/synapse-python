from typing import Union

from synapse.utils.ndtp import ElectricalBroadbandData, SpiketrainData

SynapseData = Union[SpiketrainData, ElectricalBroadbandData]
