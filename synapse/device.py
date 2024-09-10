import grpc
from google.protobuf.empty_pb2 import Empty

from synapse.api.status_pb2 import StatusCode
from synapse.api.synapse_pb2_grpc import SynapseDeviceStub
from synapse.config import Config

DEFAULT_SYNAPSE_PORT = 647


class Device(object):
    sockets = None

    def __init__(self, uri):
        if len(uri.split(":")) != 2:
            self.uri = uri + f":{DEFAULT_SYNAPSE_PORT}"
        else:
            self.uri = uri

        self.channel = grpc.insecure_channel(self.uri)
        self.rpc = SynapseDeviceStub(self.channel)

    def start(self):
        try:
            response = self.rpc.Start(Empty())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            print("Error: ", e.details())
        return False

    def stop(self):
        try:
            response = self.rpc.Stop(Empty())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            print("Error: ", e.details())
        return False

    def info(self):
        try:
            response = self.rpc.Info(Empty())
            return response
        except grpc.RpcError as e:
            print("Error: ", e.details())
            return None

    def query(self, query):
        try:
            response = self.rpc.Query(query)
            return response
        except grpc.RpcError as e:
            print("Error: ", e.details())
            return None

    def configure(self, config: Config):
        assert isinstance(config, Config), "config must be an instance of Config"

        config.set_device(self)
        try:
            response = self.rpc.Configure(config.to_proto())
            if self._handle_status_response(response):
                return response
        except grpc.RpcError as e:
            print("Error: ", e.details())
        return False

    def _handle_status_response(self, status):
        if status.code != StatusCode.kOk:
            print("Error %d: %s" % (status.code, status.message))
            return False
        else:
            self.sockets = status.sockets
            return True
