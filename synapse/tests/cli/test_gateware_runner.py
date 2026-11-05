"""Public SDK runner contract: prefer native build artifacts, fall back to extracted."""

from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def gateware():
    return importlib.import_module("synapse.cli.gateware")


@pytest.fixture()
def peripheral_dir(tmp_path):
    pd = tmp_path / "myplugin"
    (pd / "src" / "gateware").mkdir(parents=True)
    license_file = tmp_path / "license.dat"
    license_file.write_text("FEATURE radiant ...")
    return pd, license_file


@pytest.fixture()
def successful_build(gateware, monkeypatch):
    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)


def _bitstreams_dir(peripheral_dir):
    bitstreams = peripheral_dir / "src" / "gateware" / "build" / "bitstreams"
    bitstreams.mkdir(parents=True, exist_ok=True)
    return bitstreams


def test_runner_raises_when_license_unset_and_does_not_invoke_docker(
    gateware, peripheral_dir, monkeypatch
):
    pd, _ = peripheral_dir
    called = []

    def fake_run(argv, *args, **kwargs):
        called.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    with pytest.raises(gateware.LicenseUnsetError):
        gateware.run_gateware_build(str(pd), "myplugin-gateware:latest-arm64", env={})

    assert called == []


def test_runner_returns_native_only_output(gateware, peripheral_dir, successful_build):
    pd, license_file = peripheral_dir
    native = _bitstreams_dir(pd) / "sdk_gateware.bit"
    native.write_bytes(b"\x96\x01\x80\x7f")

    selected = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert Path(selected) == native
    assert Path(selected).read_bytes() == b"\x96\x01\x80\x7f"


def test_runner_ignores_newer_extracted_decoy(
    gateware, peripheral_dir, successful_build
):
    pd, license_file = peripheral_dir
    bitstreams = _bitstreams_dir(pd)
    native = bitstreams / "sdk_gateware.bit"
    native.write_bytes(b"\x96\x01\x80\x7f")
    extracted = bitstreams / "sdk_gateware_extracted.bit"
    extracted.write_bytes(b"\x69\x80\x01\xfe")
    os.utime(native, (1_000_000, 1_000_000))
    os.utime(extracted, (3_000_000, 3_000_000))

    selected = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert Path(selected) == native
    assert Path(selected).read_bytes() == b"\x96\x01\x80\x7f"


def test_runner_returns_newest_native_candidate(
    gateware, peripheral_dir, successful_build
):
    pd, license_file = peripheral_dir
    bitstreams = _bitstreams_dir(pd)
    older = bitstreams / "sdk_old.bit"
    newest = bitstreams / "sdk_new.bit"
    extracted = bitstreams / "sdk_new_extracted.bit"
    for timestamp, bit, payload in (
        (1_000_000, older, b"old native"),
        (2_000_000, newest, b"new native"),
        (3_000_000, extracted, b"extracted decoy"),
    ):
        bit.write_bytes(payload)
        os.utime(bit, (timestamp, timestamp))

    selected = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert Path(selected) == newest
    assert Path(selected).read_bytes() == b"new native"


def test_runner_falls_back_to_extracted_when_no_native_image(
    gateware, peripheral_dir, successful_build
):
    pd, license_file = peripheral_dir
    extracted = _bitstreams_dir(pd) / "sdk_gateware_extracted.bit"
    extracted.write_bytes(b"extracted")

    selected = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert Path(selected).is_absolute()
    assert Path(selected) == extracted
    assert Path(selected).read_bytes() == b"extracted"


def test_runner_falls_back_to_newest_extracted_candidate(
    gateware, peripheral_dir, successful_build
):
    pd, license_file = peripheral_dir
    bitstreams = _bitstreams_dir(pd)
    older = bitstreams / "sdk_old_extracted.bit"
    newest = bitstreams / "sdk_new_extracted.bit"
    for timestamp, bit, payload in (
        (2_000_000, newest, b"new extracted"),
        (1_000_000, older, b"old extracted"),
    ):
        bit.write_bytes(payload)
        os.utime(bit, (timestamp, timestamp))

    selected = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert Path(selected) == newest
    assert Path(selected).read_bytes() == b"new extracted"


def test_runner_ignores_newer_non_sdk_and_non_bit_files(
    gateware, peripheral_dir, successful_build
):
    pd, license_file = peripheral_dir
    bitstreams = _bitstreams_dir(pd)
    native = bitstreams / "sdk_gateware.bit"
    native.write_bytes(b"native")
    os.utime(native, (1_000_000, 1_000_000))
    for name in ("gateware.bit", "sdk_gateware.summary.json", "sdk_gateware.mcs"):
        decoy = bitstreams / name
        decoy.write_bytes(b"decoy")
        os.utime(decoy, (3_000_000, 3_000_000))

    selected = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert Path(selected) == native


def test_runner_raises_when_only_non_candidate_files_emitted(
    gateware, peripheral_dir, successful_build
):
    pd, license_file = peripheral_dir
    bitstreams = _bitstreams_dir(pd)
    for name in ("gateware.bit", "sdk_gateware.summary.json", "sdk_gateware.mcs"):
        (bitstreams / name).write_bytes(b"decoy")

    with pytest.raises(FileNotFoundError):
        gateware.run_gateware_build(
            str(pd),
            "myplugin-gateware:latest-arm64",
            env={"LM_LICENSE_FILE": str(license_file)},
        )


def test_runner_raises_when_no_bit_emitted(gateware, peripheral_dir, successful_build):
    pd, license_file = peripheral_dir
    _bitstreams_dir(pd)

    with pytest.raises(FileNotFoundError):
        gateware.run_gateware_build(
            str(pd),
            "myplugin-gateware:latest-arm64",
            env={"LM_LICENSE_FILE": str(license_file)},
        )
