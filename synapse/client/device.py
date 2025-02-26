import grpc
from google.protobuf.empty_pb2 import Empty
import logging

from synapse.api.status_pb2 import StatusCode, Status
from synapse.api.synapse_pb2_grpc import SynapseDeviceStub
from synapse.client.config import Config

DEFAULT_SYNAPSE_PORT = 647


class Device(object):
    sockets = None

    def __init__(self, uri, verbose=False):
        if len(uri.split(":")) != 2:
            self.uri = uri + f":{DEFAULT_SYNAPSE_PORT}"
        else:
            self.uri = uri

        self.channel = grpc.insecure_channel(self.uri)
        self.rpc = SynapseDeviceStub(self.channel)

        self.logger = logging.getLogger(__name__)
        level = logging.DEBUG if verbose else logging.ERROR
        self.logger.setLevel(level)

    def start(self):
        try:
            response = self.rpc.Start(Empty())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            self.logger.debug("Error: %s", e.details())
        return False

    def start_with_status(self) -> Status:
        try:
            response = self.rpc.Start(Empty())
            return response
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
        return None

    def stop(self):
        try:
            response = self.rpc.Stop(Empty())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
        return False

    def stop_with_status(self) -> Status:
        try:
            return self.rpc.Stop(Empty())
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
            return None

    def info(self):
        try:
            response = self.rpc.Info(Empty())
            self._handle_status_response(response.status)
            return response
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
            return None

    def query(self, query):
        try:
            response = self.rpc.Query(query)
            return response
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
            return None

    def configure(self, config: Config):
        assert isinstance(config, Config), "config must be an instance of Config"

        config.set_device(self)
        try:
            response = self.rpc.Configure(config.to_proto())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
        return False
    
    def configure_with_status(self, config: Config) -> Status:
        assert isinstance(config, Config), "config must be an instance of Config"

        config.set_device(self)
        try:
            response = self.rpc.Configure(config.to_proto())
            return response
        except grpc.RpcError as e:
            self.logger.error("Error: %s", e.details())
            return None

    def _handle_status_response(self, status):
        if status.code != StatusCode.kOk:
            self.logger.error("Error %d: %s", status.code, status.message)
            return False
        else:
            self.sockets = status.sockets
            return True
