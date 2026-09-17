from __future__ import annotations
from typing import AsyncGenerator, Optional, Union
import grpc
from google.protobuf.empty_pb2 import Empty
import logging
from datetime import datetime

from synapse.api.logging_pb2 import (
    LogQueryResponse,
    LogQueryRequest,
    LogLevel,
    TailLogsRequest,
)
from synapse.api.query_pb2 import StreamQueryRequest, StreamQueryResponse
from synapse.api.status_pb2 import StatusCode, Status
from synapse.api.synapse_pb2_grpc import SynapseDeviceStub
from synapse.api.device_pb2 import (
    UpdateDeviceSettingsRequest,
    UpdateDeviceSettingsResponse,
)
from synapse.api.app_pb2 import (
    ListAppsRequest,
    ListAppsResponse,
)
from synapse.client.config import Config
from synapse.utils.log import log_level_to_pb

DEFAULT_SYNAPSE_PORT = 647


class Device(object):
    def __init__(self, uri, verbose=False, raise_rpc_errors=False):
        if not uri:
            raise ValueError("URI cannot be empty or none")
        if len(uri.split(":")) != 2:
            self.uri = uri + f":{DEFAULT_SYNAPSE_PORT}"
        else:
            self.uri = uri

        self.channel = grpc.insecure_channel(self.uri)
        self.rpc = SynapseDeviceStub(self.channel)
        self.raise_rpc_errors = raise_rpc_errors

        self.logger = logging.getLogger(__name__)
        level = logging.DEBUG if verbose else logging.ERROR
        self.logger.setLevel(level)

    def start(self):
        try:
            response = self.rpc.Start(Empty())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
        return False

    def start_with_status(self) -> Status:
        try:
            response = self.rpc.Start(Empty())
            return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def stop(self):
        try:
            response = self.rpc.Stop(Empty())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
        return False

    def stop_with_status(self) -> Status:
        try:
            return self.rpc.Stop(Empty())
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def info(self):
        try:
            response = self.rpc.Info(Empty())
            self._handle_status_response(response.status)
            return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def query(self, query):
        try:
            response = self.rpc.Query(query)
            return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def configure(self, config: Config):
        assert isinstance(config, Config), "config must be an instance of Config"

        config.set_device(self)
        try:
            response = self.rpc.Configure(config.to_proto())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
        return False

    def configure_with_status(self, config: Config) -> Status:
        assert isinstance(config, Config), "config must be an instance of Config"

        config.set_device(self)
        try:
            response = self.rpc.Configure(config.to_proto())
            return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def get_name(self) -> Optional[str]:
        info = self.info()
        return info.name if info else None

    def get_logs(
        self,
        log_level: Union[str, LogLevel] = "INFO",
        since_ms: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Optional[LogQueryResponse]:
        try:
            request = LogQueryRequest()
            request.min_level = log_level_to_pb(log_level)

            if since_ms is not None:
                request.since_ms = since_ms
            else:
                if start_time:
                    request.start_time_ns = int(start_time.timestamp() * 1e9)
                if end_time:
                    request.end_time_ns = int(end_time.timestamp() * 1e9)

            response = self.rpc.GetLogs(request)
            return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def get_logs_with_status(
        self,
        log_level: Union[str, LogLevel] = LogLevel.LOG_LEVEL_INFO,
        since_ms: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Optional[Status]:
        try:
            request = LogQueryRequest()
            request.min_level = log_level_to_pb(log_level)

            if since_ms is not None:
                request.since_ms = since_ms
            else:
                if start_time:
                    request.start_time_ns = int(start_time.timestamp() * 1e9)
                if end_time:
                    request.end_time_ns = int(end_time.timestamp() * 1e9)

            return self.rpc.GetLogs(request)
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def tail_logs(
        self, log_level: Union[str, LogLevel] = LogLevel.LOG_LEVEL_INFO
    ) -> AsyncGenerator[LogQueryResponse, None]:
        try:
            request = TailLogsRequest()
            request.min_level = log_level_to_pb(log_level)
            return self.rpc.TailLogs(request)
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def stream_query(
        self, stream_request: StreamQueryRequest
    ) -> AsyncGenerator[StreamQueryResponse, None]:
        try:
            for response in self.rpc.StreamQuery(stream_request):
                yield response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            yield StreamQueryResponse(code=StatusCode.kQueryFailed)
        except Exception as e:
            self.logger.error("Stream query failed: %s", e)
            yield StreamQueryResponse(code=StatusCode.kQueryFailed)

    def update_device_settings(
        self, request: UpdateDeviceSettingsRequest
    ) -> Optional[UpdateDeviceSettingsResponse]:
        try:
            return self.rpc.UpdateDeviceSettings(request)

        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None
        except Exception as e:
            self.logger.error("Settings update failed: %s", e)
            return None

    def list_apps(self) -> Optional[ListAppsResponse]:
        """List installed applications on the device."""
        try:
            response = self.rpc.ListApps(ListAppsRequest())
            return response
        except grpc.RpcError as e:
            self._handle_rpc_error(e)
            return None

    def _handle_status_response(self, status):
        if status.code != StatusCode.kOk:
            self.logger.error("Error %d: %s", status.code, status.message)
            return False
        else:
            return True

    def _handle_rpc_error(self, error: grpc.RpcError) -> None:
        if self.raise_rpc_errors:
            raise error
        self.logger.error("Error: %s", error.details())
