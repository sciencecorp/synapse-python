import grpc
import logging

from synapse.server.nodes import (
    StreamIn,
    StreamOut,
    OpticalStimulation,
    ElectricalBroadband,
)
from synapse.api.node_pb2 import (
    NodeConnection,
)
from synapse.api.synapse_pb2 import (
    DeviceConfiguration,
    DeviceInfo,
)
from synapse.api.status_pb2 import Status, StatusCode, DeviceState
from synapse.api.query_pb2 import QueryResponse
from synapse.api.node_pb2 import NodeType
from synapse.api.synapse_pb2_grpc import (
    SynapseDeviceServicer,
    add_SynapseDeviceServicer_to_server,
)


async def serve(server_name, device_serial, rpc_port) -> None:
    server = grpc.aio.server()
    add_SynapseDeviceServicer_to_server(
        SynapseServicer(server_name, device_serial), server
    )
    server.add_insecure_port("[::]:%d" % rpc_port)
    await server.start()
    await server.wait_for_termination()


NODE_TYPE_OBJECT_MAP = {
    NodeType.kStreamIn: StreamIn,
    NodeType.kStreamOut: StreamOut,
    NodeType.kOpticalStim: OpticalStimulation,
    NodeType.kElectricalBroadband: ElectricalBroadband,
}


class SynapseServicer(SynapseDeviceServicer):
    """Provides methods that implement functionality of a Synapse device server."""

    state = DeviceState.kInitializing
    configuration = None
    connections = []
    nodes = []

    def __init__(self, name, serial):
        self.name = name
        self.serial = serial

    def Info(self, request, context):
        logging.info("Info()")
        connections = [
            NodeConnection(src_node_id=src, dst_node_id=dst)
            for src, dst in self.connections
        ]
        return DeviceInfo(
            name=self.name,
            serial=self.serial,
            synapse_version=10,
            firmware_version=1,
            status=Status(
                message=None,
                code=StatusCode.kOk,
                sockets=self._sockets_status_info(),
                state=self.state,
            ),
            peripherals=[],
            configuration=DeviceConfiguration(
                nodes=[node.config() for node in self.nodes], connections=connections
            ),
        )

    def Configure(self, request, context):
        logging.info("Configure()")
        if not self._reconfigure(request):
            return Status(
                message="Failed to configure",
                code=StatusCode.kUndefinedError,
                sockets=self._sockets_status_info(),
                state=self.state,
            )

        return Status(
            message=None,
            code=StatusCode.kOk,
            sockets=self._sockets_status_info(),
            state=self.state,
        )

    def Start(self, request, context):
        logging.info("Start()")
        if not self._start_streaming():
            return Status(
                message="Failed to start streaming",
                code=StatusCode.kUndefinedError,
                sockets=self._sockets_status_info(),
                state=self.state,
            )
        return Status(
            message=None,
            code=StatusCode.kOk,
            sockets=self._sockets_status_info(),
            state=self.state,
        )

    def Stop(self, request, context):
        logging.info("Stop()")
        if not self._stop_streaming():
            return Status(
                message="Failed to stop streaming",
                code=StatusCode.kUndefinedError,
                sockets=self._sockets_status_info(),
                state=self.state,
            )
        return Status(
            message=None,
            code=StatusCode.kOk,
            sockets=self._sockets_status_info(),
            state=self.state,
        )

    def Query(self, request, context):
        logging.info("Query()")

        if self.state != DeviceState.kRunning:
            return QueryResponse(
                data=None,
                status=Status(
                    message="Device is not running",
                    code=StatusCode.kUndefinedError,
                    sockets=self._sockets_status_info(),
                    state=self.state,
                ),
            )

        # handle query

        return QueryResponse(
            data=[1, 2, 3, 4, 5],
            status=Status(
                message=None,
                code=StatusCode.kOk,
                sockets=self._sockets_status_info(),
                state=self.state,
            ),
        )

    def _reconfigure(self, configuration):
        self.state = DeviceState.kInitializing

        logging.info("Reconfiguring device... with", configuration)
        for node in self.nodes:
            node.stop()

        self.nodes = []
        self.connections = []

        logging.info("Creating nodes...")
        for node in configuration.nodes:
            if node.type not in list(NODE_TYPE_OBJECT_MAP.keys()):
                logging.error("Unknown node type: %s" % NodeType.Name(node.type))
                logging.error("Failed to configure.")
                return False

            config_key = node.WhichOneof("config")
            config = getattr(node, config_key) if config_key else None

            logging.info("Creating %s node(%d)" % (NodeType.Name(node.type), node.id))
            node = NODE_TYPE_OBJECT_MAP[node.type](node.id)
            node.configure(config)
            self.nodes.append(node)

        for connection in configuration.connections:
            source_node = next(
                (node for node in self.nodes if node.id == connection.src_node_id), None
            )
            target_node = next(
                (node for node in self.nodes if node.id == connection.dst_node_id), None
            )
            if not source_node or not target_node:
                logging.error(
                    "Server: failed to connect nodes %d -> %d"
                    % (connection.src_node_id, connection.dst_node_id)
                )
                return False
            source_node.emit_data = target_node.on_data_received

            self.connections.append([source_node.id, target_node.id])
        logging.info(
            "%d nodes received, %d currently loaded"
            % (len(configuration.nodes), len(self.nodes))
        )
        self.configuration = configuration

        self.state = DeviceState.kStopped

        return True

    def _start_streaming(self):
        logging.info("Server: starting streaming...")
        for node in self.nodes:
            node.start()
        self.state = DeviceState.kRunning
        logging.info("Server: streaming started.")
        return True

    def _stop_streaming(self):
        if self.state != DeviceState.kRunning:
            return False
        logging.info("Server: stopping streaming...")
        for node in self.nodes:
            node.stop()
        self.state = DeviceState.kStopped
        logging.info("Server: streaming stopped.")
        return True

    def _sockets_status_info(self):
        return [node.node_socket() for node in self.nodes if node.socket]
