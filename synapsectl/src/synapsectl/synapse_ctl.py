#!/usr/bin/env python
import grpc
from google.protobuf.empty_pb2 import Empty
from generated.api.synapse_pb2_grpc import SynapseDeviceStub
from generated.api.synapse_pb2 import DeviceInfo
# from generated.node_pb2 import NodeOptions

def main():
    with grpc.insecure_channel('0.0.0.0:50051') as channel:
        stub = SynapseDeviceStub(channel)
        response = stub.Info(Empty())

        print(response)

if __name__ == '__main__':
    main()