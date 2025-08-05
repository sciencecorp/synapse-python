import asyncio
import random
import time

import zmq

from synapse.api.node_pb2 import NodeType
from synapse.api.nodes.broadband_source_pb2 import BroadbandSourceConfig
from synapse.server.nodes.base import BaseNode
from synapse.api.tap_pb2 import TapConnection, TapType
from synapse.api.datatype_pb2 import BroadbandFrame
from synapse.server.status import Status
from synapse.utils.ndtp_types import ElectricalBroadbandData

def r_sample(bit_width: int):
    return random.randint(0, 2**bit_width - 1)


class BroadbandSource(BaseNode):
    def __init__(self, id):
        super().__init__(id, NodeType.kBroadbandSource)
        self.__config: BroadbandSourceConfig = None
        self.zmq_context = None
        self.zmq_socket = None
        self.seq_number = 0
        self.iface_ip = None
        self.port = None

    def config(self):
        c = super().config()
        if self.__config:
            c.broadband_source.CopyFrom(self.__config)
        return c

    def configure(
        self, config: BroadbandSourceConfig = BroadbandSourceConfig()
    ) -> Status:
        self.__config = config
        return Status()

    async def run(self):
        if not self.__config:
            self.logger.error("node not configured")
            return

        c = self.__config

        if not c.HasField("signal") or not c.signal:
            self.logger.error("node signal not configured")
            return

        if not c.signal.HasField("electrode") or not c.signal.electrode:
            self.logger.error("node signal electrode not configured")
            return

        e = c.signal.electrode
        if not e.channels:
            self.logger.error("node signal electrode channels not configured")
            return

        if not self.zmq_context:
            if not self.iface_ip:
                self.logger.error("iface_ip not configured")
                return

            self.zmq_context = zmq.Context()
            self.zmq_socket = self.zmq_context.socket(zmq.PUB)
            self.port = self.zmq_socket.bind_to_random_port(f"tcp://{self.iface_ip}")

        channels = e.channels
        bit_width = c.bit_width if c.bit_width else 4
        sample_rate_hz = c.sample_rate_hz if c.sample_rate_hz else 16000

        t_last_ns = time.time_ns()
        while self.running:
            await asyncio.sleep(0.01)

            now = time.time_ns()
            elapsed_ns = now - t_last_ns
            n_samples = int(sample_rate_hz * elapsed_ns / 1e9)
            samples = [[ch.id, [r_sample(bit_width) for _ in range(n_samples)]] for ch in channels]

            try:
                # for backwards compatibility
                data = ElectricalBroadbandData(
                    bit_width=bit_width,
                    is_signed=False,
                    sample_rate=sample_rate_hz,
                    t0=t_last_ns,
                    samples=samples
                )
                await self.emit_data(data)

                # send data over tap
                for i in range(n_samples):
                    frame = BroadbandFrame(
                        timestamp_ns = t_last_ns + int(i * 1e9 / sample_rate_hz),
                        sequence_number = self.seq_number,
                        frame_data = [chan_samples[i] for _, chan_samples in samples],
                        sample_rate_hz = sample_rate_hz,
                    )
                    try:
                        self.zmq_socket.send(frame.SerializeToString())
                        self.seq_number += 1
                    except Exception as e:
                        self.logger.error(f"Error sending data: {e}")

                t_last_ns = now
            except Exception as e:
                print(f"Error sending data: {e}")

    def stop(self):
        """Clean up ZMQ resources."""
        if self.zmq_socket:
            self.zmq_socket.close()
            self.zmq_socket = None

        if self.zmq_context:
            self.zmq_context.destroy()
            self.zmq_context = None

        return super().stop()

    def configure_iface_ip(self, iface_ip):
        self.iface_ip = iface_ip

    def tap_connections(self):
        return [
            TapConnection(
                name="broadband_source_sim",
                endpoint=f"tcp://{self.iface_ip}:{self.port}",
                message_type="synapse.BroadbandFrame",
                tap_type=TapType.TAP_TYPE_PRODUCER,
            )
        ]

