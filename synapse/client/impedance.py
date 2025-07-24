import logging
from typing import AsyncGenerator, List, Optional
from synapse.api.query_pb2 import QueryRequest, ImpedanceMeasurement
from synapse.api.status_pb2 import StatusCode

class Impedance(object):
    def __init__(self, uri, verbose=False):
        self.uri = uri
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    def get_impedance(self, electrode_ids: Optional[List[int]] = None) -> AsyncGenerator[ImpedanceMeasurement, None]:
        """Get impedance for a list of electrodes.

        Args:
            electrode_ids (List[int], optional): List of electrode IDs to query.
                If None or empty, query all electrodes. Defaults to None.

        Returns:
            list: List of ImpedanceMeasurement objects.
        """
        from synapse.client.device import Device

        device = Device(self.uri, self.verbose)

        request = QueryRequest()
        request.query_type = QueryRequest.kImpedance
        if electrode_ids:
            request.impedance_query.electrode_ids.extend(electrode_ids)
        else:
            # To query all, we send an empty ImpedanceQuery
            request.impedance_query.SetInParent()

        # return device.stream_query(request)
        for response in device.stream_query(request):
            if response.code != StatusCode.kOk:
                self.logger.error(f"Error getting impedance: {response.message}")
                return []
            else:
                yield response.impedance
