#!/usr/bin/env python
import grpc
from google.protobuf.empty_pb2 import Empty
import generated.synapse_pb2_grpc as synapse_pb2_grpc

def main():
    with grpc.insecure_channel('0.0.0.0:50051') as channel:
        stub = synapse_pb2_grpc.SynapseDeviceStub(channel)
        response = stub.Info(Empty())
        print(response)

if __name__ == '__main__':
    main()