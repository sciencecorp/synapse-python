import asyncio
class MulticastDiscoveryProtocol:
    def __init__(
        self, server_name, serial, rpc_port=647
    ):
        self.server_name = server_name
        self.serial = serial
        self.rpc_port = rpc_port

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        command = data.decode("ascii")

        if command == "DISCOVER":
            print(
                "Received DISCOVER command from {!r}".format(addr)
            )

            print("  -- Replying")
            self.transport.sendto(
                "ID {} SYN1.0 {} {}".format(
                    self.serial, self.rpc_port, self.server_name
                ).encode("ascii"),
                addr,
            )
        else:
            print("Unknown command: {!r}".format(command))


class BroadcastDiscoveryProtocol:
    def __init__(self, discovery_port, server_name, serial, rpc_port=647, broadcast_interval=1):
        self.server_name = server_name
        self.serial = serial
        self.rpc_port = rpc_port
        self.broadcast_interval = broadcast_interval
        self.discovery_port = discovery_port

    def connection_made(self, transport):
        self.transport = transport
        asyncio.create_task(self.broadcast_loop())

    async def broadcast_loop(self):
        while True:
            self.broadcast_message()
            await asyncio.sleep(self.broadcast_interval)

    def broadcast_message(self):
        message = "ID {} SYN1.0 {} {}".format(self.serial, self.rpc_port, self.server_name).encode("ascii")
        self.transport.sendto(message, ('255.255.255.255', self.discovery_port))

    def datagram_received(self, data, addr):
        pass

    def connection_lost(self, exc):
        pass
