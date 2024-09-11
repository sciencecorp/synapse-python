import grpc
import logging

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


async def serve(
    server_name, device_serial, rpc_port, iface_ip, node_object_map, peripherals
) -> None:
    server = grpc.aio.server()
    add_SynapseDeviceServicer_to_server(
        SynapseServicer(
            server_name, device_serial, iface_ip, node_object_map, peripherals
        ),
        server,
    )
    server.add_insecure_port("[::]:%d" % rpc_port)
    await server.start()
    await server.wait_for_termination()


class SynapseServicer(SynapseDeviceServicer):
    """Provides methods that implement functionality of a Synapse device server."""

    state = DeviceState.kInitializing
    configuration = None
    connections = []
    nodes = []

    def __init__(self, name, serial, iface_ip, node_object_map, peripherals):
        self.name = name
        self.serial = serial
        self.iface_ip = iface_ip
        self.node_object_map = node_object_map
        self.peripherals = peripherals
        self.logger = logging.getLogger("server")

    def Info(self, request, context):
        self.logger.info("Info()")
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
            peripherals=self.peripherals,
            configuration=DeviceConfiguration(
                nodes=[node.config() for node in self.nodes], connections=connections
            ),
        )

    def Configure(self, request, context):
        self.logger.info("Configure()")
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
        self.logger.info("Start()")
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
        self.logger.info("Stop()")
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
        self.logger.info("Query()")

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

        self.logger.info("Reconfiguring device...")
        self.logger.info("Configuration: %s", str(configuration))

        for node in self.nodes:
            node.stop()

        self.nodes = []
        self.connections = []

        self.logger.info("Creating nodes...")
        for node in configuration.nodes:
            if node.type not in list(self.node_object_map.keys()):
                self.logger.error(
                    "Unsupported node type: %s" % NodeType.Name(node.type)
                )
                self.logger.error("Failed to configure.")
                return False

            config_key = node.WhichOneof("config")
            config = getattr(node, config_key) if config_key else None

            self.logger.info(
                "Creating %s node(%d)" % (NodeType.Name(node.type), node.id)
            )
            node = self.node_object_map[node.type](node.id)
            status = node.configure(config, self.iface_ip)

            if not status.ok():
                self.logger.warning(
                    f"Failed to configure node {node.id}: {status.message()}"
                )
            else:
                self.nodes.append(node)

        for connection in configuration.connections:
            source_node = next(
                (node for node in self.nodes if node.id == connection.src_node_id), None
            )
            target_node = next(
                (node for node in self.nodes if node.id == connection.dst_node_id), None
            )
            if not source_node or not target_node:
                self.logger.error(
                    "failed to connect nodes %d -> %d"
                    % (connection.src_node_id, connection.dst_node_id)
                )
                return False

            self.logger.info(
                f"Connecting node {source_node.id} to node {target_node.id}"
            )
            source_node.emit_data = target_node.on_data_received
            self.connections.append([source_node.id, target_node.id])

        self.logger.info(
            "%d nodes received, %d currently loaded"
            % (len(configuration.nodes), len(self.nodes))
        )
        self.configuration = configuration

        self.state = DeviceState.kStopped

        return True

    def _start_streaming(self):
        self.logger.info("starting streaming...")
        for node in self.nodes:
            node.start()
        self.state = DeviceState.kRunning
        self.logger.info("streaming started.")
        return True

    def _stop_streaming(self):
        if self.state != DeviceState.kRunning:
            return False
        self.logger.info("stopping streaming...")
        for node in self.nodes:
            node.stop()
        self.state = DeviceState.kStopped
        self.logger.info("streaming stopped.")
        return True

    def _sockets_status_info(self):
        return [node.node_socket() for node in self.nodes if node.socket]
