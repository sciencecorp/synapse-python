from io import StringIO
import logging

import grpc
import pytest
from rich.console import Console

from synapse.cli.errors import error_message, run_action
from synapse.client.config import Config
from synapse.client.device import Device


class FakeRpcError(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNAUTHENTICATED

    def details(self):
        return "not paired with this device; pair first"

    def __str__(self):
        return (
            "<_MultiThreadedRendezvous status=UNAUTHENTICATED "
            'debug_error_string="internal transport details">'
        )


def capture_console():
    output = StringIO()
    return Console(file=output, color_system=None), output


def test_rpc_error_message_hides_transport_diagnostics():
    message = error_message(FakeRpcError())

    assert message == "not paired with this device; pair first"
    assert "_MultiThreadedRendezvous" not in message
    assert "debug_error_string" not in message


def test_verbose_rpc_error_message_includes_status_but_not_transport_repr():
    message = error_message(FakeRpcError(), verbose=True)

    assert message == ("gRPC UNAUTHENTICATED: not paired with this device; pair first")
    assert "_MultiThreadedRendezvous" not in message
    assert "debug_error_string" not in message


def test_semantic_error_does_not_print_usage():
    console, output = capture_console()

    def fail():
        raise ValueError("configuration is not valid for this device")

    exit_code = run_action(fail, console=console)

    assert exit_code == 1
    assert output.getvalue() == ("Error: configuration is not valid for this device\n")
    assert "usage:" not in output.getvalue()
    assert "Uncaught" not in output.getvalue()


def test_rpc_error_is_concise_and_fails():
    console, output = capture_console()

    def fail():
        raise FakeRpcError()

    exit_code = run_action(fail, console=console)

    assert exit_code == 1
    assert output.getvalue() == "Error: not paired with this device; pair first\n"


def test_false_command_result_is_a_failure():
    console, _ = capture_console()

    assert run_action(lambda: False, console=console) == 1


def test_configure_rpc_error_reaches_cli_boundary_without_duplicate_message():
    class FailingRpc:
        def Configure(self, _request):
            raise FakeRpcError()

    device = Device.__new__(Device)
    device.rpc = FailingRpc()
    device.raise_rpc_errors = True
    console, output = capture_console()

    exit_code = run_action(
        lambda: device.configure_with_status(Config()),
        console=console,
    )

    assert exit_code == 1
    assert output.getvalue() == "Error: not paired with this device; pair first\n"
    assert "Internal error configuring device" not in output.getvalue()


def test_cli_device_configure_rpc_error_is_not_converted_to_none():
    class FailingRpc:
        def Configure(self, _request):
            raise FakeRpcError()

    device = Device.__new__(Device)
    device.rpc = FailingRpc()
    device.raise_rpc_errors = True

    with pytest.raises(FakeRpcError):
        device.configure_with_status(Config())


def test_default_device_configure_preserves_none_on_rpc_error():
    class FailingRpc:
        def Configure(self, _request):
            raise FakeRpcError()

    device = Device.__new__(Device)
    device.rpc = FailingRpc()
    device.raise_rpc_errors = False
    device.logger = logging.getLogger(__name__)

    assert device.configure_with_status(Config()) is None
