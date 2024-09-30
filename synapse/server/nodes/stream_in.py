import select
import socket
import threading
from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.stream_in_pb2 import StreamInConfig
from synapse.server.nodes.base import BaseNode
from synapse.server.status import Status
from synapse.utils.ndtp import NDTPMessage
from synapse.utils.types import ElectricalBroadbandData, SpiketrainData, SynapseData


class StreamIn(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kStreamIn)
        self.__socket = None
        self.__stop_event = threading.Event()

    def config(self):
        c = super().config()

        if self.__config:
            c.stream_in.CopyFrom(self.__config)

        return c

    def configure(self, config: StreamInConfig) -> Status:
        self.__config = config

        self.__socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 3)

        self.__socket.bind(("", 0))
        self.socket = self.__socket.getsockname()
        self.logger.info(f"listening on {self.socket}")

        return Status()

    def configure_iface_ip(self, iface_ip):
        pass

    def start(self) -> Status:
        self.logger.info("starting...")
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.start()
        self.logger.info("started")
        return Status()

    def stop(self) -> Status:
        if not hasattr(self, "thread") or not self.thread.is_alive():
            return
        self.logger.info("stopping...")
        self.__stop_event.set()
        self.thread.join()
        self.__socket.close()
        self.__socket = None
        self.logger.info("stopped")
        return Status()

    def run(self):
        self.logger.info("starting to receive data...")
        while not self.__stop_event.is_set():
            try:
                ready = select.select([self.__socket], [], [], 1)
                if ready[0]:
                    data, _ = self.__socket.recvfrom(1024)
                    unpacked = self._unpack(data)
                    self.emit_data(unpacked)
            except Exception as e:
                self.logger.error(f"Error receiving data: {e}")

        self.logger.info("exited thread")

    def _unpack(self, data: bytes) -> SynapseData:
        u = None
        try:
            u = NDTPMessage.unpack(data)
        except Exception as e:
            self.logger.error(f"Failed to unpack NDTPMessage: {e}")
            return data

        h = u.header
        if h.data_type == DataType.kBroadband:
            return ElectricalBroadbandData.from_ndtp_message(u)
        elif h.data_type == DataType.kSpiketrain:
            return SpiketrainData.from_ndtp_message(u)
        else:
            self.logger.error(f"Unknown data type: {h.data_type}")
            return data
