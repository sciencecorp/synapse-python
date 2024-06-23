import grpc
from google.protobuf.empty_pb2 import Empty
from generated.api.synapse_pb2_grpc import SynapseDeviceStub
from generated.api.synapse_pb2 import DeviceInfo

class SynapseDevice(object):
  def __init__(self, uri):
    self.uri = uri

    self.channel = grpc.insecure_channel(uri)
    self.rpc = SynapseDeviceStub(self.channel)

  def start(self):
    request = self.rpc.Start(Empty())
    return request

  def stop(self):
    request = self.rpc.Stop(Empty())
    return request

  def info(self):
    request = self.rpc.Info(Empty())
    return request

  def configure(self, config):
    pass
