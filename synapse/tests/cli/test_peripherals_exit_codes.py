"""Process exit status of ``synapsectl peripherals build`` / ``... deploy``.

Each case runs the real ``synapsectl`` entry point on a command line and
asserts the integer it hands to ``sys.exit``. Only the edges that would touch
Docker, the gateware toolchain, fpm or a device are faked.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import synapse.cli
from synapse.tests.cli.conftest import fake_fpm_run

HALVES = ["driver", "gateware", "both"]
PLUGIN = "intan_rhd2132"
URI = "10.0.0.1"

# conftest.py stubs synapse.cli.__main__, so load the real file under another name.
_spec = importlib.util.spec_from_file_location(
    "synapse_cli_main_for_exit_codes",
    Path(synapse.cli.__file__).with_name("__main__.py"),
)
cli_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli_main)

with_and_without_uri = pytest.mark.parametrize(
    "uri_args", [[], ["-u", URI]], ids=["no-uri", "with-uri"]
)


@pytest.fixture()
def peripherals():
    return importlib.import_module("synapse.cli.peripherals")


@pytest.fixture()
def synapsectl(monkeypatch):
    """Return ``run(argv) -> exit status`` for the real ``synapsectl`` main."""

    def run(argv):
        monkeypatch.setattr(sys, "argv", ["synapsectl", *argv])
        return cli_main.main()

    return run


@pytest.fixture()
def plugin_dir(tmp_path):
    """A single-project plugin repo with a valid manifest and gateware project."""
    pd = tmp_path / PLUGIN
    (pd / "build" / "aarch64").mkdir(parents=True)
    (pd / "manifest.json").write_text(
        json.dumps(
            {
                "name": PLUGIN,
                "version": "0.1.0",
                "install": {"target": f"/usr/lib/scifi/plugins/{PLUGIN}.so"},
            }
        )
    )
    # The driver half's runtime libs and .so, as a driver build leaves them.
    for fname in (
        f"{PLUGIN}.so",
        "libscifi-peripheral-sdk.so",
        "libscifi-peripheral-sdk.so.0",
        "libscifi-peripheral-sdk.so.0.1.0",
    ):
        (pd / "build" / "aarch64" / fname).write_text("fake")
    gw = pd / "src" / "gateware"
    gw.mkdir(parents=True)
    (gw / "peripheral.yaml").write_text("radiant_version: '2024.2'\n")
    return pd


def _emit_bitstream(peripheral_dir, *args, **kwargs):
    """Stand-in for a gateware build that emits an image plus its summary."""
    out = os.path.join(str(peripheral_dir), "src", "gateware", "build", "bitstreams")
    os.makedirs(out, exist_ok=True)
    bit = os.path.join(out, f"sdk_{PLUGIN}.bit")
    with open(bit, "w", encoding="utf-8") as fh:
        fh.write("fake-bit")
    with open(
        os.path.join(out, f"sdk_{PLUGIN}.summary.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(
            {
                "usb_pid": "0x0004",
                "target_profile": "via-devkit",
                "project": {"name": "gateware", "git_sha": "e6890a3"},
            },
            fh,
        )
    return bit


@pytest.fixture()
def toolchain(peripherals, plugin_dir, monkeypatch):
    """Fake Docker, the driver/gateware builds, fpm and the device: all succeed.

    The real .deb packagers run; fpm is faked to drop the .deb into dist/.
    Returns the list of ``(uri, deb)`` deploy calls.
    """
    deploys: list = []

    def deploy_package(uri, deb, *args, **kwargs):
        deploys.append((uri, deb))
        return True

    monkeypatch.setattr(peripherals, "ensure_docker", lambda: True)
    monkeypatch.setattr(
        peripherals,
        "build_docker_image",
        lambda *a, **kw: {"driver": "fake-driver:arm64", "gateware": "fake-gw:arm64"},
    )
    monkeypatch.setattr(peripherals, "build_peripheral_so", lambda *a, **kw: True)
    monkeypatch.setattr(peripherals.gateware, "run_gateware_build", _emit_bitstream)
    monkeypatch.setattr(
        peripherals.subprocess,
        "run",
        fake_fpm_run(os.path.join(str(plugin_dir), "dist"), []),
    )
    monkeypatch.setattr(peripherals, "deploy_package", deploy_package)
    return deploys


# --- Failure injectors: each breaks one precondition or one build step. ------


def _docker_missing(peripherals, plugin_dir, monkeypatch):
    monkeypatch.setattr(peripherals, "ensure_docker", lambda: False)


def _manifest_missing(peripherals, plugin_dir, monkeypatch):
    (plugin_dir / "manifest.json").unlink()


def _manifest_not_json(peripherals, plugin_dir, monkeypatch):
    (plugin_dir / "manifest.json").write_text("{not json")


def _manifest_without_name(peripherals, plugin_dir, monkeypatch):
    (plugin_dir / "manifest.json").write_text(json.dumps({"version": "0.1.0"}))


def _driver_build_fails(peripherals, plugin_dir, monkeypatch):
    monkeypatch.setattr(peripherals, "build_peripheral_so", lambda *a, **kw: False)


def _gateware_raises(error):
    def inject(peripherals, plugin_dir, monkeypatch):
        def fail(*args, **kwargs):
            raise error

        monkeypatch.setattr(peripherals.gateware, "run_gateware_build", fail)

    return inject


def _fpm_fails(peripherals, plugin_dir, monkeypatch):
    def run(argv, *args, **kwargs):
        rc = 1 if "fpm" in argv else 0
        return subprocess.CompletedProcess(list(argv), rc, b"", b"fpm: error")

    monkeypatch.setattr(peripherals.subprocess, "run", run)


# (id, injector, halves the failure applies to)
FAILURES = [
    # Preconditions, checked before any half builds.
    ("docker-missing", _docker_missing, HALVES),
    ("manifest-missing", _manifest_missing, HALVES),
    ("manifest-not-json", _manifest_not_json, HALVES),
    ("manifest-without-name", _manifest_without_name, HALVES),
    # A requested half fails to build or package.
    ("driver-build-fails", _driver_build_fails, ["driver", "both"]),
    (
        "gateware-build-fails",
        _gateware_raises(subprocess.CalledProcessError(2, ["axon-peripheral-sdk"])),
        ["gateware", "both"],
    ),
    (
        "gateware-emits-no-image",
        _gateware_raises(FileNotFoundError("build emitted no bitstream")),
        ["gateware", "both"],
    ),
    ("deb-packaging-fails", _fpm_fails, HALVES),
]
FAILURE_CASES = [
    pytest.param(inject, half, id=f"{case_id}-{half}")
    for case_id, inject, halves in FAILURES
    for half in halves
]


# --- peripherals build -------------------------------------------------------


@pytest.mark.parametrize("inject, half", FAILURE_CASES)
def test_build_exits_nonzero_when_a_requested_half_cannot_be_built(
    synapsectl, peripherals, plugin_dir, toolchain, monkeypatch, inject, half
):
    inject(peripherals, plugin_dir, monkeypatch)

    assert synapsectl(["peripherals", "build", half, str(plugin_dir)]) != 0


@pytest.mark.parametrize("half", HALVES)
def test_build_exits_zero_when_every_requested_half_builds(
    synapsectl, plugin_dir, toolchain, half
):
    assert synapsectl(["peripherals", "build", half, str(plugin_dir)]) == 0
    assert list((plugin_dir / "dist").glob("*.deb")), "a .deb must be produced"


# --- peripherals deploy ------------------------------------------------------


@with_and_without_uri
def test_deploy_exits_nonzero_when_package_does_not_exist(
    synapsectl, plugin_dir, toolchain, tmp_path, uri_args
):
    missing = tmp_path / "absent_0.1.0_arm64.deb"

    status = synapsectl(
        [
            *uri_args,
            "peripherals",
            "deploy",
            "both",
            str(plugin_dir),
            "--package",
            str(missing),
        ]
    )

    assert status != 0
    assert toolchain == [], "nothing may be deployed"


@with_and_without_uri
@pytest.mark.parametrize("inject, half", FAILURE_CASES)
def test_deploy_exits_nonzero_when_the_build_fails(
    synapsectl, peripherals, plugin_dir, toolchain, monkeypatch, inject, half, uri_args
):
    inject(peripherals, plugin_dir, monkeypatch)

    status = synapsectl([*uri_args, "peripherals", "deploy", half, str(plugin_dir)])

    assert status != 0
    assert toolchain == [], "nothing may be deployed after a failed build"


@pytest.mark.parametrize("half", HALVES)
def test_deploy_without_uri_exits_zero_after_building(
    synapsectl, plugin_dir, toolchain, half
):
    assert synapsectl(["peripherals", "deploy", half, str(plugin_dir)]) == 0
    assert list((plugin_dir / "dist").glob("*.deb")), "packages must be created"
    assert toolchain == [], "no URI means nothing is deployed"


@pytest.mark.parametrize("half", HALVES)
def test_deploy_exits_zero_when_every_package_deploys(
    synapsectl, plugin_dir, toolchain, half
):
    assert synapsectl(["-u", URI, "peripherals", "deploy", half, str(plugin_dir)]) == 0
    expected = 2 if half == "both" else 1
    assert [uri for uri, _ in toolchain] == [URI] * expected


@pytest.mark.parametrize(
    "half, failing_call",
    [("driver", 0), ("gateware", 0), ("both", 0), ("both", 1)],
    ids=["driver", "gateware", "both-first-package", "both-second-package"],
)
def test_deploy_exits_nonzero_when_any_package_fails_to_deploy(
    synapsectl, peripherals, plugin_dir, toolchain, monkeypatch, half, failing_call
):
    call_index = itertools.count()

    def deploy_package(uri, deb, *args, **kwargs):
        return next(call_index) != failing_call

    monkeypatch.setattr(peripherals, "deploy_package", deploy_package)

    assert synapsectl(["-u", URI, "peripherals", "deploy", half, str(plugin_dir)]) != 0


@with_and_without_uri
def test_deploy_existing_package_exits_zero(
    synapsectl, plugin_dir, toolchain, tmp_path, uri_args
):
    deb = tmp_path / "prebuilt_0.1.0_arm64.deb"
    deb.write_text("fake-deb")

    status = synapsectl(
        [
            *uri_args,
            "peripherals",
            "deploy",
            "both",
            str(plugin_dir),
            "--package",
            str(deb),
        ]
    )

    assert status == 0
    assert toolchain == ([(URI, str(deb))] if uri_args else [])
