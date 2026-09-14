"""Tests for `synapsectl pair` / `unpair`.

The `pair` handshake itself needs a live device on the other end of a gRPC
stream (challenge code, then a human tapping Allow) -- there is no meaningful
way to unit test that without faking most of grpc, so it is left to the
on-device validation task. What's tested here:

  - argparse registration: `pair` and `unpair` (including its optional
    positional `identifier`) show up wired to the right functions with the
    right flags -- exactly what a --help typo would not be caught by any
    other test.
  - `unpair`'s two paths, both reachable through the real CLI:
      * `unpair <serial-or-name>` -- purely local, no network at all. Covers
        matching by serial, matching by name, no match, and an ambiguous
        name match.
      * `unpair --uri <device>` (no positional) -- contacts the device via
        the open `Info` RPC for the authoritative serial. Covers found, not
        found, and unreachable.
      * both given -- the positional wins and the device is never contacted.
      * neither given -- a usage hint instead of a crash.
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


def _args(uri=None, verbose=False, identifier=None):
    return argparse.Namespace(uri=uri, verbose=verbose, identifier=identifier)


def _patch_device(monkeypatch, device):
    monkeypatch.setattr(auth_module.syn, "Device", lambda uri, verbose: device)


def _forbid_device_contact(monkeypatch):
    """Fail the test if `unpair` tries to construct a Device at all."""

    def _fail(uri, verbose):
        raise AssertionError("unpair should not have contacted the device")

    monkeypatch.setattr(auth_module.syn, "Device", _fail)


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
    assert unpair_args.identifier is None

    unpair_args = parser.parse_args(["unpair", "sci-fi-1234"])
    assert unpair_args.func is auth_module.unpair
    assert unpair_args.identifier == "sci-fi-1234"


# --- unpair <identifier>: local-only, no network ----------------------------


def test_unpair_by_identifier_matches_serial(env_file, console_log, monkeypatch):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _forbid_device_contact(monkeypatch)

    auth_module.unpair(_args(identifier="NYX1512-0042"))

    assert client_auth.token_for_serial("NYX1512-0042") is None
    assert any("Forgot the token" in line for line in console_log)


def test_unpair_by_identifier_matches_name(env_file, console_log, monkeypatch):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _forbid_device_contact(monkeypatch)

    auth_module.unpair(_args(identifier="sci-fi-1234"))

    assert client_auth.token_for_serial("NYX1512-0042") is None
    assert any("Forgot the token" in line for line in console_log)


def test_unpair_by_identifier_no_match_lists_stored_entries(
    env_file, console_log, monkeypatch
):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _forbid_device_contact(monkeypatch)

    auth_module.unpair(_args(identifier="nonexistent"))

    # Nothing removed, and the real entry is surfaced so the user can see the
    # right spelling.
    assert client_auth.token_for_serial("NYX1512-0042") == "f3a9c1"
    assert any("No stored entry matches" in line for line in console_log)
    assert any("sci-fi-1234" in line for line in console_log)


def test_unpair_by_identifier_ambiguous_name_removes_nothing(
    env_file, console_log, monkeypatch
):
    client_auth.save_token("NYX1512-0042", "dup-name", "token-a")
    client_auth.save_token("NYX1512-0099", "dup-name", "token-b")
    _forbid_device_contact(monkeypatch)

    auth_module.unpair(_args(identifier="dup-name"))

    # Nothing removed: we refuse to guess between the two matches.
    assert client_auth.token_for_serial("NYX1512-0042") == "token-a"
    assert client_auth.token_for_serial("NYX1512-0099") == "token-b"
    assert any("matches more than one" in line for line in console_log)
    assert any("NYX1512-0042" in line for line in console_log)
    assert any("NYX1512-0099" in line for line in console_log)


# --- unpair --uri <device>: contacts the device for the authoritative serial


def test_unpair_via_uri_removes_the_stored_token_when_found(
    env_file, console_log, monkeypatch
):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _patch_device(
        monkeypatch, _FakeDevice(info=_FakeInfo(serial="NYX1512-0042", name="sci-fi-1234"))
    )

    auth_module.unpair(_args(uri="10.0.0.5"))

    assert client_auth.token_for_serial("NYX1512-0042") is None
    assert any("Forgot the token" in line for line in console_log)


def test_unpair_via_uri_reports_no_token_when_device_never_paired(
    env_file, console_log, monkeypatch
):
    _patch_device(
        monkeypatch, _FakeDevice(info=_FakeInfo(serial="NYX1512-0042", name="sci-fi-1234"))
    )

    auth_module.unpair(_args(uri="10.0.0.5"))

    assert client_auth.load_tokens() == {}
    assert any("No stored token" in line for line in console_log)


def test_unpair_via_uri_when_device_unreachable_does_not_guess(
    env_file, console_log, monkeypatch
):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _patch_device(
        monkeypatch,
        _FakeDevice(error=_FakeRpcError(grpc.StatusCode.UNAVAILABLE, "no route")),
    )

    auth_module.unpair(_args(uri="10.0.0.5"))

    # Nothing removed -- the old silent name-fallback against --uri is gone;
    # the message instead points at `unpair <serial-or-name>`.
    assert client_auth.token_for_serial("NYX1512-0042") == "f3a9c1"
    assert any("Could not reach the device" in line for line in console_log)
    assert any("unpair <serial-or-name>" in line for line in console_log)


# --- both / neither given ---------------------------------------------------


def test_unpair_prefers_identifier_and_never_contacts_device_when_both_given(
    env_file, console_log, monkeypatch
):
    client_auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    _forbid_device_contact(monkeypatch)

    auth_module.unpair(_args(uri="10.0.0.5", identifier="sci-fi-1234"))

    assert client_auth.token_for_serial("NYX1512-0042") is None
    assert any("Forgot the token" in line for line in console_log)


def test_unpair_with_neither_uri_nor_identifier_prints_hint(
    env_file, console_log, monkeypatch
):
    _forbid_device_contact(monkeypatch)

    auth_module.unpair(_args())

    assert any("Specify a device" in line for line in console_log)
