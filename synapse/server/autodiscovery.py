class MulticastDiscoveryProtocol:

    def __init__(
        self, server_name, serial, security_mode=False, passphrase=None, rpc_port=647
    ):
        self.server_name = server_name
        self.serial = serial
        self.security_mode = security_mode
        self.passphrase = passphrase
        self.rpc_port = rpc_port

    def connection_made(self, transport):
        self.transport = transport

    def check_security(self, code):
        return self.security_mode == False or code == self.passphrase

    def datagram_received(self, data, addr):
        command, code = data.decode("ascii").split()

        if command == "DISCOVER":
            print(
                "Received DISCOVER command from {!r} with code {!r}".format(addr, code)
            )

            if self.check_security(code):
                print("  -- Security pass, replying")
                self.transport.sendto(
                    "ID {} SYN1.0 {} {}".format(
                        self.serial, self.rpc_port, self.server_name
                    ).encode("ascii"),
                    addr,
                )
            else:
                print("  -- Security fail, ignoring")
        else:
            print("Unknown command: {!r}".format(command))
