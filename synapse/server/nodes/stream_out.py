import queue
import socket
import struct
import threading
from typing import List, Tuple
from synapse.server.nodes.base import BaseNode
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_out_pb2 import StreamOutConfig
from synapse.server.status import Status, StatusCode

PORT = 6480
MULTICAST_TTL = 3


class StreamOut(BaseNode):
    __n = 0

    def __init__(self, id):
        super().__init__(id, NodeType.kStreamOut)
        self.__i = StreamOut.__n
        StreamOut.__n += 1
        self.__stop_event = threading.Event()
        self.__data_queue = queue.Queue()
        self.__sequence_number = 0
        self.__iface_ip = None
        self.__config = None

    def config(self):
        c = super().config()

        if self.__config:
            c.stream_out.CopyFrom(self.__config)

        return c

    def configure(self, config: StreamOutConfig) -> Status:
        if not self.__iface_ip:
            return Status(StatusCode.kUndefinedError, "No interface IP specified")

        if config.use_multicast and not config.multicast_group:
            return Status(StatusCode.kUndefinedError, "No multicast group specified")

        self.__config = config

        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        port = PORT + self.__i

        self.__socket.bind((self.__iface_ip, port))

        if config.use_multicast:
            mreq = struct.pack(
                "=4sl", socket.inet_aton(config.multicast_group), socket.INADDR_ANY
            )
            self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self.__socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL
            )

            self.socket = [config.multicast_group, port]
            self.logger.info(
                f"created multicast socket on {self.socket}, group {config.multicast_group}"
            )
        else:
            self.socket = [self.__iface_ip, port]
            self.logger.info(
                f"created multicast socket on {self.socket}"
            )


        return Status()

    def configure_iface_ip(self, iface_ip):
        self.__iface_ip = iface_ip

    def start(self):
        self.logger.info("starting...")
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.info("started")
        return Status()

    def stop(self):
        self.logger.info("stopping...")
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return

        self.__stop_event.set()
        self.thread.join()
        self.__socket.close()
        self.__socket = None
        self.logger.info("stopped")
        return Status()

    def on_data_received(self, data):
        self.__data_queue.put(data)

    def run(self):
        self.logger.info("starting to send data...")
        while not self.__stop_event.is_set():
            if not self.socket:
                self.logger.error("socket not configured")
                return
            try:
                data = self.__data_queue.get(True, 1)
            except queue.Empty:
                self.logger.warning("queue is empty")
                continue

            if data is None or len(data) < 1:
                continue

            if data[0] == DataType.kBroadband:
                # detect data type arriving at you (should be packaged in `data` above)
                # encode it appropriately for NDTP
                data_type, t0, channel_data = data

                for channel in channel_data:
                    encoded_data = self.serialize_broadband_ndtp(t0, channel)
                    if len(encoded_data) == 0:
                        continue

                    try:
                        self.__socket.sendto(encoded_data, (self.socket[0], self.socket[1]))
                        self.__sequence_number = (self.__sequence_number + 1) & 0xFFFF

                    except Exception as e:
                        self.logger.error(f"Error sending data: {e}")
            else:
                self.logger.error(f"Unsupported data type, dropping: {data[0]}")
                continue

    def serialize_broadband_ndtp(self, t0, data: Tuple[int, List[int]]) -> bytes:
        if len(data) == 0:
            return bytes()

        result = bytearray()
        result.extend(
            struct.pack("=IiqHh", 0xC0FFEE00, DataType.kBroadband, t0, self.__sequence_number, 1)
        )

        channel_id = data[0] - 1
        samples = data[1]
        result.extend(struct.pack("ii", channel_id, len(samples)))

        for sample in samples:
            result.extend(struct.pack("h", sample))

        return bytes(result)
