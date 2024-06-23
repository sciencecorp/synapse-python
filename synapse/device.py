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
    try:
      request = self.rpc.Start(Empty())
      return request
    except grpc.RpcError as e:
      print(e.details())
      return None

  def stop(self):
    try:
      request = self.rpc.Stop(Empty())
      return request
    except grpc.RpcError as e:
      print(e.details())
      return None

  def info(self):
    try:
      request = self.rpc.Info(Empty())
      return request
    except grpc.RpcError as e:
      print(e.details())
      return None

  def configure(self, config):
    pass
