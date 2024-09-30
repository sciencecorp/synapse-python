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
