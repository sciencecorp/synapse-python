import grpc
from google.protobuf import text_format
from google.protobuf.empty_pb2 import Empty
from synapse.generated.api.synapse_pb2 import StatusCode
from synapse.generated.api.synapse_pb2_grpc import SynapseDeviceStub


class Device(object):
    sockets = None

    def __init__(self, uri):
        self.uri = uri

        self.channel = grpc.insecure_channel(uri)
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

    def configure(self, config):
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
