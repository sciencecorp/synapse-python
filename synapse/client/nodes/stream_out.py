import logging
import socket
import traceback
from typing import Optional, Tuple

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.stream_out_pb2 import StreamOutConfig
from synapse.client.node import Node
from synapse.utils.ndtp import NDTPMessage
from synapse.utils.ndtp_types import (
    ElectricalBroadbandData,
    SpiketrainData,
    SynapseData,
    NDTPHeader,
)

DEFAULT_STREAM_OUT_PORT = 50038
STREAM_OUT_TIMEOUT_SEC = 1  # seconds


# Try to get the current user's ip for setting the destination address
def get_client_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # This won't actually establish a connection, but helps us figure out the ip
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception as e:
        logging.error(f"Failed to get client IP: {e}")
        return None
    finally:
        s.close()
    return local_ip


class StreamOut(Node):
    type = NodeType.kStreamOut

    def __init__(
        self,
        label=None,
        destination_address=None,
        destination_port=None,
        read_timeout=STREAM_OUT_TIMEOUT_SEC,
    ):
        self.__socket = None
        self.__label = label
        self.__read_timeout = read_timeout

        # If we have been passed a None for destination address, try to resolve it
        if not destination_address:
            self.__destination_address = get_client_ip()
        else:
            self.__destination_address = destination_address

        if not destination_port:
            self.__destination_port = DEFAULT_STREAM_OUT_PORT
        else:
            self.__destination_port = destination_port

    def read(self) -> Tuple[Optional[Tuple[NDTPHeader, SynapseData]], int]:
        if self.__socket is None:
            if self.open_socket() is None:
                return None
        try:
            data, _ = self.__socket.recvfrom(8192)
            bytes_read = len(data)
        except socket.timeout:
            logging.warning("StreamOut socket timed out.")
            return None
        return self._unpack(data), bytes_read

    def open_socket(self):
        logging.info(
            f"Opening socket at {self.__destination_address}:{self.__destination_port}"
        )
        if self.device is None:
            logging.error("Node has no device")
            return None

        # UDP socket
        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        # Allow reuse for easy restart
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Try to set a large recv buffer
        SOCKET_BUFSIZE_BYTES = 5 * 1024 * 1024  # 5MB
        self.__socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFSIZE_BYTES
        )
        recvbuf = self.__socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        if recvbuf < SOCKET_BUFSIZE_BYTES:
            logging.warning(
                f"Could not set socket buffer size to {SOCKET_BUFSIZE_BYTES}. Current size is {recvbuf}. Consider increasing the system limit."
            )

        # Set a timeout
        self.__socket.settimeout(self.__read_timeout)

        # Bind to the destination address (our ip) and port
        try:
            self.__socket.bind((self.__destination_address, self.__destination_port))
        except Exception as e:
            logging.error(
                f"Failed to bind to {self.__destination_address}:{self.__destination_port}: {e}"
            )
            return None
        return self.__socket

    def _to_proto(self):
        n = NodeConfig()

        o = StreamOutConfig()
        if self.__label:
            o.label = self.__label
        else:
            o.label = "Stream Out"

        if self.__destination_address:
            o.udp_unicast.destination_address = self.__destination_address

        if self.__destination_port:
            o.udp_unicast.destination_port = self.__destination_port

        n.stream_out.CopyFrom(o)
        return n

    def _unpack(self, data: bytes) -> Tuple[NDTPHeader, SynapseData]:
        u = None
        try:
            u = NDTPMessage.unpack(data)

        except Exception as e:
            logging.error(f"Failed to unpack NDTPMessage: {e}")
            traceback.print_exc()

        h = u.header
        if h.data_type == DataType.kBroadband:
            return h, ElectricalBroadbandData.from_ndtp_message(u)
        elif h.data_type == DataType.kSpiketrain:
            return h, SpiketrainData.from_ndtp_message(u)
        else:
            logging.error(f"Unknown data type: {h.data_type}")
            return h, data

    @staticmethod
    def _from_proto(proto: Optional[StreamOutConfig]):
        if proto is None:
            return StreamOut()

        if not isinstance(proto, StreamOutConfig):
            raise ValueError("proto is not of type StreamOutConfig")

        # We currently only support udp unicast
        selected_transport = proto.WhichOneof("transport")

        if selected_transport is None:
            # Set the defaults
            destination_address = get_client_ip()
            destination_port = DEFAULT_STREAM_OUT_PORT
            logging.info(
                f"Requesting StreamOut to: {destination_address}:{destination_port}"
            )
            return StreamOut(proto.label, destination_address, destination_port)
        elif selected_transport == "udp_unicast":
            dest_address = proto.udp_unicast.destination_address
            dest_port = proto.udp_unicast.destination_port
            if dest_address == "":
                dest_address = get_client_ip()
            if dest_port == 0:
                dest_port = DEFAULT_STREAM_OUT_PORT
            logging.info(
                f"Using user provided StreamOut destination: {dest_address}:{dest_port}"
            )
            return StreamOut(proto.label, dest_address, dest_port)
        else:
            logging.error(f"Unsupported transport: {selected_transport}")
            return None
