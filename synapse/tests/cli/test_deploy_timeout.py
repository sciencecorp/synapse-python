"""``deploy.deploy_package`` forwards its timeout as the DeployApp deadline."""

from __future__ import annotations

import importlib
from unittest import mock

import pytest

from synapse.api.app_pb2 import AppDeployResponse
from synapse.api.status_pb2 import StatusCode

_NO_DEADLINE = object()


class _RecordingRpc:
    def __init__(self):
        self.deploy_calls: list = []

    def DeployApp(self, request_iterator, **kwargs):
        # Drain the stream like a real server so the whole package is sent.
        list(request_iterator)
        self.deploy_calls.append(kwargs)
        return iter([AppDeployResponse(status=StatusCode.kOk, message="ok")])


@pytest.fixture()
def deploy():
    return importlib.import_module("synapse.cli.deploy")


@pytest.fixture()
def rpc(deploy, monkeypatch):
    rpc = _RecordingRpc()
    device = mock.MagicMock()
    device.rpc = rpc
    monkeypatch.setattr(deploy.syn, "Device", lambda *a, **k: device)
    return rpc


@pytest.fixture()
def deb(tmp_path):
    path = tmp_path / "axon-gateware-x_0.1.0_arm64.deb"
    path.write_bytes(b"\x00DEB" * 1024)
    return str(path)


def _deadline(rpc):
    assert len(rpc.deploy_calls) == 1, "one DeployApp stream per package"
    return rpc.deploy_calls[0].get("timeout", _NO_DEADLINE)


@pytest.mark.parametrize("seconds", [1, 30.5, 900])
def test_deploy_package_passes_timeout_to_deploy_app(deploy, rpc, deb, seconds):
    deploy.deploy_package("10.0.0.2", deb, timeout=seconds)
    assert _deadline(rpc) == seconds


def test_deploy_package_without_timeout_sets_no_deadline(deploy, rpc, deb):
    """Positional two-argument calls keep working and impose no deadline."""
    deploy.deploy_package("10.0.0.2", deb)
    assert _deadline(rpc) in (None, _NO_DEADLINE)


def test_deploy_package_explicit_none_timeout_sets_no_deadline(deploy, rpc, deb):
    deploy.deploy_package("10.0.0.2", deb, timeout=None)
    assert _deadline(rpc) in (None, _NO_DEADLINE)
