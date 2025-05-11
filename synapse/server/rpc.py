import logging
from pathlib import Path
import time
from typing import Callable, List
import asyncio

import grpc

from synapse.api.node_pb2 import NodeConnection, NodeType
from synapse.api.logging_pb2 import LogLevel, LogQueryResponse
from synapse.api.query_pb2 import QueryResponse
from synapse.api.status_pb2 import DeviceState, Status, StatusCode
from synapse.api.synapse_pb2 import DeviceConfiguration, DeviceInfo
from synapse.api.synapse_pb2_grpc import (
    SynapseDeviceServicer,
    add_SynapseDeviceServicer_to_server,
)
from synapse.utils.log import (
    StreamingLogHandler,
    init_file_handler,
    str_to_log_entry,
)


LOG_FILEPATH = str(Path.home() / ".science" / "synapse" / "logs" / "server.log")


def _read_api_version():
    try:
        with open(str(Path(__file__).parent.parent / "api" / "version.txt")) as f:
            return f.read().strip()
    except (FileNotFoundError, IOError):
        return None


async def serve(
    server_name,
    device_serial,
    rpc_port,
    iface_ip,
    node_object_map,
    peripherals,
    services: List[Callable[[str, grpc.aio.Server], None]] = [],
) -> None:
    server = grpc.aio.server()
    add_SynapseDeviceServicer_to_server(
        SynapseServicer(
            server_name, device_serial, iface_ip, node_object_map, peripherals
        ),
        server,
    )

    for service in services:
        service(device_serial, server)

    server.add_insecure_port("[::]:%d" % rpc_port)
    await server.start()
    await server.wait_for_termination()


class SynapseServicer(SynapseDeviceServicer):
    """Provides methods that implement functionality of a Synapse device server."""

    state = DeviceState.kStopped
    configuration = None
    connections = []
    nodes = []

    def __init__(self, name, serial, iface_ip, node_object_map, peripherals):
        self.name = name
        self.serial = serial
        self.node_object_map = node_object_map
        self.peripherals = peripherals
        self.logger = logging.getLogger("server")

        self.active_streams = set()
        self.stream_handler = StreamingLogHandler(self._broadcast_log)
        logging.getLogger().addHandler(self.stream_handler)
        init_file_handler(self.logger, LOG_FILEPATH)

        self.synapse_api_version = _read_api_version()

    async def Info(self, request, context):
        self.logger.info("Info()")
        connections = [
            NodeConnection(src_node_id=src, dst_node_id=dst)
            for src, dst in self.connections
        ]
        return DeviceInfo(
            name=self.name,
            serial=self.serial,
            synapse_version=self._synapse_api_version(),
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

    async def Configure(self, request, context):
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

    async def Start(self, request, context):
        self.logger.info("Start()")
        if not await self._start_streaming():
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

    async def Stop(self, request, context):
        self.logger.info("Stop()")
        if not await self._stop_streaming():
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

    async def Query(self, request, context):
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

    async def GetLogs(self, request, context):
        self.logger.info("GetLogs()")
        try:
            min_level = (
                request.min_level if request.min_level else LogLevel.LOG_LEVEL_INFO
            )
            entries = []

            if request.since_ms:
                current_time_ns = time.time_ns()
                start_time_ns = current_time_ns - (request.since_ms * 1_000_000)
                end_time_ns = current_time_ns
            else:
                start_time_ns = request.start_time_ns if request.start_time_ns else 0
                end_time_ns = (
                    request.end_time_ns if request.end_time_ns else time.time_ns()
                )

            if not Path(LOG_FILEPATH).exists():
                self.logger.warning(f"Log file not found at {LOG_FILEPATH}")
                await context.abort(grpc.StatusCode.NOT_FOUND, "no log file found")

            try:
                with open(LOG_FILEPATH, "r") as f:
                    for line in f:
                        try:
                            entry = str_to_log_entry(line)
                            if not entry:
                                continue
                            if start_time_ns and entry.timestamp_ns < start_time_ns:
                                continue
                            if end_time_ns and entry.timestamp_ns >= end_time_ns:
                                continue
                            if entry.level < min_level:
                                continue
                            entries.append(entry)
                        except Exception:
                            self.logger.warning(
                                f"failed to parse log line: {line} - skipping"
                            )
                            continue

            except FileNotFoundError:
                self.logger.warning(f"Log file not found at {LOG_FILEPATH}")
                await context.abort(grpc.StatusCode.UNKNOWN, "failed to open log file")

            return LogQueryResponse(entries=entries)

        except Exception as e:
            self.logger.error(f"Error getting logs: {str(e)}")
            return LogQueryResponse(entries=[])

    async def TailLogs(self, request, context):
        self.logger.info("TailLogs()")
        try:
            min_level = (
                request.min_level if request.min_level else LogLevel.LOG_LEVEL_INFO
            )

            log_queue = asyncio.Queue(maxsize=100)

            def handle_log(record: str):
                try:
                    log_queue.put_nowait(record)
                except asyncio.QueueFull:
                    self.logger.warning("Log queue full - dropping log")

            self.active_streams.add(handle_log)

            try:
                while True:
                    try:
                        formatted_record = await log_queue.get()

                        try:
                            entry = str_to_log_entry(formatted_record)
                            if not entry:
                                continue
                            if entry.level < min_level:
                                continue

                            yield entry

                        except Exception as e:
                            self.logger.warning(
                                f"Failed to parse log record: {formatted_record} - {str(e)}"
                            )
                            continue

                    except asyncio.CancelledError:
                        break

            finally:
                self.active_streams.remove(handle_log)

        except Exception as e:
            self.logger.error(f"Error tailing logs: {str(e)}")
            await context.abort(
                grpc.StatusCode.UNKNOWN, f"failed to tail logs: {str(e)}"
            )
            return

    def __del__(self):
        if hasattr(self, "stream_handler"):
            logging.getLogger().removeHandler(self.stream_handler)

    def _broadcast_log(self, formatted_record: str) -> None:
        for stream in self.active_streams.copy():
            try:
                stream(formatted_record)
            except Exception as e:
                self.logger.warning(f"Failed to send log to client: {e}")

    def _reconfigure(self, configuration):
        self.state = DeviceState.kInitializing

        self.logger.info("Reconfiguring device...")
        self.logger.info("Configuration: %s", str(configuration))

        for node in self.nodes:
            node.stop()

        self.nodes = []
        self.connections = []

        self.logger.info("Creating nodes...")
        valid_node_types = list(self.node_object_map.keys())
        for node in configuration.nodes:
            if node.type not in valid_node_types:
                self.logger.error(
                    f"Unsupported node type: {NodeType.Name(node.type)} ({node.type}) (valid nodes: {[NodeType.Name(t) for t in valid_node_types]}) "
                )
                self.logger.error("Failed to configure.")
                return False

            config_key = node.WhichOneof("config")
            config = getattr(node, config_key) if config_key else None

            self.logger.info(
                "Creating %s node(%d)" % (NodeType.Name(node.type), node.id)
            )
            node = self.node_object_map[node.type](node.id)
            if node.type in [NodeType.kStreamIn]:
                node.configure_iface_ip(self.iface_ip)

            status = node.configure(config)

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
            source_node.add_downstream_node(target_node)
            self.connections.append([source_node.id, target_node.id])

        self.logger.info(
            "%d nodes received, %d currently loaded"
            % (len(configuration.nodes), len(self.nodes))
        )
        self.configuration = configuration

        self.state = DeviceState.kStopped

        return True

    async def _start_streaming(self):
        self.logger.info("Starting streaming...")
        for node in self.nodes:
            node.start()
        self.state = DeviceState.kRunning
        self.logger.info("Streaming started.")
        return True

    async def _stop_streaming(self):
        if self.state != DeviceState.kRunning:
            return False
        self.logger.info("Stopping streaming...")
        for node in self.nodes:
            node.stop()
        self.state = DeviceState.kStopped
        self.logger.info("Streaming stopped.")
        return True

    def _sockets_status_info(self):
        return [node.node_socket() for node in self.nodes if node.socket]

    def _synapse_api_version(self):
        if self.synapse_api_version is None:
            return 0
        try:
            major, minor, patch = map(int, self.synapse_api_version.split("."))
            return (major & 0x3FF) << 20 | (minor & 0x3FF) << 10 | (patch & 0x3FF)
        except Exception:
            return 0
