"""Tests for `synapsectl pair` / `unpair`.

The `pair` handshake itself needs a live device on the other end of a gRPC
stream (challenge code, then a human tapping Allow) -- there is no meaningful
way to unit test that without faking most of grpc, so it is left to the
on-device validation task. What's tested here:

  - argparse registration: `pair` and `unpair` show up wired to the right
    functions with the right flags (this is exactly what a --help typo would
    not be caught by any other test).
  - `unpair`'s local-removal logic, which is pure enough to test directly:
    found, not found, device-unreachable-fallback-by-name, and the ambiguous
    case where the fallback can't tell which entry is meant.
"""

import argparse
import contextlib

import grpc
import pytest

from synapse.cli import auth as auth_module
from synapse.client import auth as client_auth


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".scifi-env"
    monkeypatch.setenv("SCIFI_ENV_FILE", str(path))
    return path


@pytest.fixture
def console_log(monkeypatch):
    """Replace rich's Console with something that just records plain text."""
    lines = []

    class _FakeConsole:
        def print(self, *args, **kwargs):
            lines.append(" ".join(str(a) for a in args))

        def status(self, *args, **kwargs):
            return contextlib.nullcontext()

    monkeypatch.setattr(auth_module, "Console", lambda: _FakeConsole())
    return lines


class _FakeRpcError(grpc.RpcError):
    def __init__(self, code, details):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


class _FakeInfo:
    def __init__(self, serial, name):
        self.serial = serial
        self.name = name


class _FakeRpc:
    def __init__(self, info=None, error=None):
        self._info = info
        self._error = error

    def Info(self, request, timeout=None):
        if self._error is not None:
            raise self._error
        return self._info


class _FakeDevice:
    """Stands in for `syn.Device(uri, verbose)`."""

    def __init__(self, info=None, error=None):
        self.rpc = _FakeRpc(info=info, error=error)


def _args(uri="10.0.0.5", verbose=False):
    return argparse.Namespace(uri=uri, verbose=verbose)


def _patch_device(monkeypatch, device):
    monkeypatch.setattr(auth_module.syn, "Device", lambda uri, verbose: device)


# --- argparse registration -------------------------------------------------


def test_pair_and_unpair_are_registered():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(title="Commands")
    auth_module.add_commands(subparsers)

    pair_args = parser.parse_args(["pair"])
    assert pair_args.func is auth_module.pair
    assert pair_args.label is None

    pair_args = parser.parse_args(["pair", "--label", "calvin@laptop"])
    assert pair_args.label == "calvin@laptop"

    unpair_args = parser.parse_args(["unpair"])
    assert unpair_args.func is auth_module.unpair


# --- unpair: found / not found ----------------------------------------------


def test_unpair_removes_the_stored_token_when_found(env_file, console_log, monkeypatch):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _patch_device(
        monkeypatch, _FakeDevice(info=_FakeInfo(serial="NYX1512-0042", name="sci-fi-1234"))
    )

    auth_module.unpair(_args())

    assert client_auth.token_for_serial("NYX1512-0042") is None
    assert any("Forgot the token" in line for line in console_log)


def test_unpair_reports_no_token_when_device_never_paired(
    env_file, console_log, monkeypatch
):
    _patch_device(
        monkeypatch, _FakeDevice(info=_FakeInfo(serial="NYX1512-0042", name="sci-fi-1234"))
    )

    auth_module.unpair(_args())

    assert client_auth.load_tokens() == {}
    assert any("No stored token" in line for line in console_log)


# --- unpair: device unreachable, fallback by stored name --------------------


def test_unpair_falls_back_to_name_match_when_device_unreachable(
    env_file, console_log, monkeypatch
):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _patch_device(
        monkeypatch,
        _FakeDevice(error=_FakeRpcError(grpc.StatusCode.UNAVAILABLE, "no route")),
    )

    auth_module.unpair(_args(uri="sci-fi-1234"))

    assert client_auth.token_for_serial("NYX1512-0042") is None
    assert any("Forgot the token" in line for line in console_log)


def test_unpair_ambiguous_name_match_removes_nothing(env_file, console_log, monkeypatch):
    client_auth.save_token("NYX1512-0042", "dup-name", "token-a")
    client_auth.save_token("NYX1512-0099", "dup-name", "token-b")
    _patch_device(
        monkeypatch,
        _FakeDevice(error=_FakeRpcError(grpc.StatusCode.UNAVAILABLE, "no route")),
    )

    auth_module.unpair(_args(uri="dup-name"))

    # Nothing was removed: we refuse to guess between the two matches.
    assert client_auth.token_for_serial("NYX1512-0042") == "token-a"
    assert client_auth.token_for_serial("NYX1512-0099") == "token-b"
    assert any("Could not determine" in line for line in console_log)
