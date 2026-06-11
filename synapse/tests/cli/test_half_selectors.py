"""AC-11 → AC-7 / AC-8 (sub-phase 4.4), AC-12 (sub-phase 4.5), two-deb flow.

Tests the ``driver`` / ``gateware`` / ``both`` target subcommands on
``synapsectl peripherals build`` (AC-7) and ``... peripherals deploy``
(AC-8), the ``--clean`` × half-selector matrix (AC-7 body), and the
two-deb staging layout (driver deb + separate -gateware deb).

The half selectors were originally mutually-exclusive ``--driver`` /
``--gateware`` flags; they are now ``build``/``deploy`` subcommands
(``driver``/``gateware``/``both``). ``half`` still drives the handlers, so
the cases that call ``build_cmd``/``deploy_cmd`` directly are unchanged; the
argparse-surface cases parse the subcommand form.

Conventions:
  * Cases A-H cover ``peripherals build``.
  * Cases I-L cover ``peripherals deploy`` (incl. ``--package`` interaction).
  * Cases M-O exercise the two-deb staging layout under real packagers + fake fpm.
  * Cases Q-R exercise two-deb deploy streaming and error paths.

Mocking strategy mirrors the prior Tester (``test_gateware_runner.py``):
  * ``synapse.cli.peripherals.subprocess.run`` -> recorder
  * ``synapse.cli.peripherals.build_peripheral_so`` -> recorder returning True
  * ``synapse.cli.peripherals.build_peripheral_deb`` -> recorder returning True
  * ``synapse.cli.peripherals.build_gateware_deb`` -> recorder returning True
  * ``synapse.cli.peripherals.gateware.run_gateware_build`` -> recorder
    returning the path of a fake ``.bit`` created under ``tmp_path``
  * ``synapse.cli.peripherals.deploy_package`` -> recorder
  * ``synapse.cli.peripherals.ensure_docker`` -> True
  * ``synapse.cli.peripherals.build_docker_image`` -> dict return
  * ``synapse.cli.peripherals.find_deb_package`` -> a fake .deb path

Tests don't need a real Docker daemon, real cmake/vcpkg, or a real Radiant
license — everything that would shell out is monkey-patched.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from synapse.tests.cli.conftest import fake_fpm_run


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def peripherals():
    """Lazy-import ``synapse.cli.peripherals``.

    Importing at module-collection time would touch the half-selector code
    paths before AC-7/AC-8 land. A fixture defers the import so a clean
    ``ImportError`` per test is more informative than a single collection
    crash that masks every case.
    """
    return importlib.import_module("synapse.cli.peripherals")


def _make_peripheral_dir(
    tmp_path,
    *,
    name: str = "intan_rhd2132",
    with_gateware: bool = True,
    with_install_target: bool = True,
):
    """Create a fake peripheral directory tree.

    Layout::

        <tmp_path>/<name>/
            manifest.json
            build/aarch64/<so_filename>             (fake .so so build_peripheral_deb finds it)
            src/gateware/                            (only if with_gateware)
            src/gateware/peripheral.yaml             (only if with_gateware)
            src/gateware/build/SENTINEL_GATEWARE     (sentinel for --clean tests)
            build/aarch64/SENTINEL_DRIVER            (sentinel for --clean tests)

    Returns the absolute path of ``<tmp_path>/<name>``.
    """
    pd = tmp_path / name
    pd.mkdir()

    # Manifest
    install: dict = {}
    if with_install_target:
        install["target"] = f"/usr/lib/scifi/plugins/{name}.so"
    manifest = {"name": name, "version": "0.1.0"}
    if install:
        manifest["install"] = install
    (pd / "manifest.json").write_text(json.dumps(manifest))

    # Driver build dir + sentinel
    driver_build = pd / "build" / "aarch64"
    driver_build.mkdir(parents=True)
    (driver_build / "SENTINEL_DRIVER").write_text("driver")
    # Fake .so so build_peripheral_deb's existence check passes if invoked.
    (driver_build / f"{name}.so").write_text("fake-so")

    # Gateware dir + sentinel
    if with_gateware:
        gw_dir = pd / "src" / "gateware"
        gw_dir.mkdir(parents=True)
        (gw_dir / "peripheral.yaml").write_text("radiant_version: '2024.2'\n")
        gw_build = gw_dir / "build"
        gw_build.mkdir()
        (gw_build / "SENTINEL_GATEWARE").write_text("gateware")
        # Also drop a fake .bit under build/bitstreams/ so run_gateware_build's
        # stub has somewhere to point.
        bs = gw_build / "bitstreams"
        bs.mkdir()
        (bs / f"sdk_{name}.bit").write_text("fake-bit")

    return pd


def _build_root_parser(peripherals):
    """Build a fresh root parser wired with `peripherals.add_commands`.

    Avoids relying on `synapse.cli.__main__` (which the conftest stubs out).
    Returns the parser; tests call ``parser.parse_args([...])``.
    """
    parser = argparse.ArgumentParser(prog="synapsectl")
    subparsers = parser.add_subparsers(dest="cmd")
    peripherals.add_commands(subparsers)
    return parser


def _install_common_stubs(peripherals, monkeypatch, tmp_path, *, fake_bit=None):
    """Stub out everything that would shell out.

    Returns a ``SimpleNamespace`` with recorders so tests can introspect.
    """
    recorders = SimpleNamespace(
        build_so_calls=[],
        run_gateware_calls=[],
        build_deb_calls=[],
        build_gateware_deb_calls=[],
        subprocess_calls=[],
        deploy_calls=[],
    )

    def fake_build_so(*args, **kwargs):
        recorders.build_so_calls.append((args, kwargs))
        return True

    def fake_build_deb(*args, **kwargs):
        recorders.build_deb_calls.append((args, kwargs))
        return True

    def fake_build_gateware_deb(*args, **kwargs):
        recorders.build_gateware_deb_calls.append((args, kwargs))
        return True

    def fake_run_gateware(*args, **kwargs):
        recorders.run_gateware_calls.append((args, kwargs))
        if fake_bit is not None:
            bit = str(fake_bit)
        else:
            path = tmp_path / "fake.bit"
            path.write_text("bit")
            bit = str(path)
        stem, _ = os.path.splitext(bit)
        with open(f"{stem}.summary.json", "w", encoding="utf-8") as fh:
            json.dump({"usb_pid": "0x0004", "project": {"name": "gateware"}}, fh)
        return bit

    def fake_subprocess_run(argv, *args, **kwargs):
        recorders.subprocess_calls.append(
            (list(argv) if isinstance(argv, list) else argv, args, kwargs)
        )
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    def fake_deploy_package(uri, deb_path):
        recorders.deploy_calls.append((uri, deb_path))
        return True

    monkeypatch.setattr(peripherals, "build_peripheral_so", fake_build_so)
    monkeypatch.setattr(peripherals, "build_peripheral_deb", fake_build_deb)
    monkeypatch.setattr(peripherals, "build_gateware_deb", fake_build_gateware_deb)
    monkeypatch.setattr(peripherals, "ensure_docker", lambda: True)
    monkeypatch.setattr(
        peripherals,
        "build_docker_image",
        lambda *a, **kw: {
            "driver": "fake-driver:latest-arm64",
            "gateware": "fake-gateware:latest-arm64",
        },
    )
    monkeypatch.setattr(peripherals.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(peripherals, "deploy_package", fake_deploy_package)

    # find_deb_package is called per deb with the version-anchored prefix
    # (e.g. "intan_rhd2132_0.1.0"), so the returned path carries the version.
    monkeypatch.setattr(
        peripherals,
        "find_deb_package",
        lambda dist_dir, package_name=None: os.path.join(
            dist_dir, f"{package_name or 'fake'}_arm64.deb"
        ),
    )

    # gateware sub-module attribute on peripherals must expose run_gateware_build.
    # The plan says peripherals.py imports gateware module-level, so we either
    # patch synapse.cli.gateware.run_gateware_build OR peripherals.gateware.run_gateware_build.
    # Patch the source-of-truth (synapse.cli.gateware) so both names resolve.
    gateware_mod = importlib.import_module("synapse.cli.gateware")
    monkeypatch.setattr(
        gateware_mod, "run_gateware_build", fake_run_gateware, raising=False
    )
    # Best-effort: also patch a `peripherals.gateware` attribute if present.
    if hasattr(peripherals, "gateware"):
        monkeypatch.setattr(
            peripherals.gateware, "run_gateware_build", fake_run_gateware, raising=False
        )

    return recorders


def _build_args(peripheral_dir, **overrides):
    """Construct an args Namespace for build_cmd."""
    ns = SimpleNamespace(
        peripheral_dir=str(peripheral_dir),
        clean=False,
        half="both",
        uri=None,
        package=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _deploy_args(peripheral_dir, **overrides):
    """Construct an args Namespace for deploy_cmd."""
    ns = SimpleNamespace(
        peripheral_dir=str(peripheral_dir),
        half="both",
        uri=None,
        package=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


# ===========================================================================
# AC-7: peripherals build flag handling
# ===========================================================================


# --- Case A: no flag -> both halves ----------------------------------------


def test_case_A_build_no_flag_runs_both_halves(peripherals, tmp_path, monkeypatch):
    """A: ``peripherals build`` with no half flag runs driver AND gateware."""
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.build_cmd(_build_args(pd, half="both"))

    assert len(recorders.build_so_calls) == 1, "driver builder should run once"
    assert len(recorders.run_gateware_calls) == 1, "gateware runner should run once"
    assert len(recorders.build_deb_calls) == 1, "driver .deb staging should run once"
    assert len(recorders.build_gateware_deb_calls) == 1, (
        "gateware .deb staging should run once"
    )


# --- Case A2: `both` subcommand parses to half="both" on build and deploy --


def test_case_A2_both_subcommand_parses_to_both(peripherals, tmp_path):
    """A2: ``build both`` and ``deploy both`` resolve ``args.half == "both"``.

    The explicit ``both`` target is the subcommand-era replacement for the old
    flagless default; it must route to the same handler with ``half="both"``.
    """
    pd = _make_peripheral_dir(tmp_path)
    parser = _build_root_parser(peripherals)

    build_args = parser.parse_args(["peripherals", "build", "both", str(pd)])
    assert getattr(build_args, "half", None) == "both"
    assert build_args.func is peripherals.build_cmd

    deploy_args = parser.parse_args(["peripherals", "deploy", "both", str(pd)])
    assert getattr(deploy_args, "half", None) == "both"
    assert deploy_args.func is peripherals.deploy_cmd


# --- Case B: build driver -> driver half only ------------------------------


def test_case_B_build_driver_skips_gateware(peripherals, tmp_path, monkeypatch):
    """B: ``build driver`` -> ``run_gateware_build`` is NEVER invoked.

    Parses via the real argparse surface: the ``driver`` subcommand must set
    ``args.half`` to ``"driver"`` and ``build_cmd`` must branch accordingly.
    """
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    parser = _build_root_parser(peripherals)
    args = parser.parse_args(["peripherals", "build", "driver", str(pd)])
    assert getattr(args, "half", None) == "driver", (
        f"args.half must be 'driver' after the 'driver' subcommand; got: "
        f"{getattr(args, 'half', None)!r}"
    )
    # Carry over fields build_cmd expects.
    args.uri = None
    if not hasattr(args, "package"):
        args.package = None
    peripherals.build_cmd(args)

    assert len(recorders.build_so_calls) == 1
    assert recorders.run_gateware_calls == [], (
        "--driver must not invoke the gateware runner"
    )
    assert len(recorders.build_deb_calls) == 1
    assert recorders.build_gateware_deb_calls == [], (
        "driver-only build must not stage a gateware deb"
    )


# --- Case C: --gateware -> gateware half only ------------------------------


def test_case_C_build_gateware_skips_driver(peripherals, tmp_path, monkeypatch):
    """C: ``--gateware`` -> cmake/vcpkg path (``build_peripheral_so``) NEVER invoked."""
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.build_cmd(_build_args(pd, half="gateware"))

    assert recorders.build_so_calls == [], (
        "--gateware must not invoke the driver builder"
    )
    assert len(recorders.run_gateware_calls) == 1
    assert recorders.build_deb_calls == [], (
        "gateware-only build must not stage the driver deb"
    )
    assert len(recorders.build_gateware_deb_calls) == 1


# --- Case D: build with an invalid target -> argparse rejects --------------


def test_case_D_build_invalid_target_is_invalid_choice_error(
    peripherals, tmp_path, capsys
):
    """D: ``build <bogus>`` -> argparse `SystemExit(2)` + "invalid choice".

    The half selectors are now subcommands, so the old ``--driver --gateware``
    mutex collision is structurally impossible: each half is a distinct verb
    and they cannot be combined. The replacement contract is that the only
    accepted targets are ``driver`` / ``gateware`` / ``both``; anything else
    is argparse's standard invalid-choice error.
    """
    parser = _build_root_parser(peripherals)
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["peripherals", "build", "neither"])

    assert excinfo.value.code == 2, (
        "argparse must reject an unknown build target with exit code 2"
    )
    captured = capsys.readouterr()
    err = captured.err.lower()
    assert "invalid choice" in err, (
        f"stderr must reference argparse's 'invalid choice'; got: {captured.err!r}"
    )
    assert "driver" in err and "gateware" in err and "both" in err, (
        f"stderr should enumerate the valid targets; got: {captured.err!r}"
    )


# --- Case D2: bare `build` (no target) prints help, builds nothing ----------


def test_case_D2_build_no_target_prints_help_and_builds_nothing(
    peripherals, tmp_path, monkeypatch, capsys
):
    """D2: ``build`` with no target -> the parent prints help; no half runs.

    Bare ``build`` resolves to the help-printing default func, so dispatching
    it must not invoke either builder.
    """
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    parser = _build_root_parser(peripherals)
    args = parser.parse_args(["peripherals", "build"])
    assert hasattr(args, "func"), "bare `build` must carry a default func"
    assert getattr(args, "half", None) is None, (
        "bare `build` must not set a half; a target subcommand is required"
    )
    args.func(args)  # the help-printing default; must not raise

    assert recorders.build_so_calls == []
    assert recorders.run_gateware_calls == []
    assert recorders.build_deb_calls == []
    assert recorders.build_gateware_deb_calls == []
    captured = capsys.readouterr()
    assert "driver" in captured.out and "gateware" in captured.out, (
        f"bare `build` should print help listing the targets; got: {captured.out!r}"
    )


# --- Case E: --clean --driver cleans only the driver tree ------------------


def test_case_E_clean_driver_does_not_touch_gateware_tree(
    peripherals, tmp_path, monkeypatch
):
    """E: ``build driver --clean`` -> driver clean fires, gateware tree untouched.

    Parses via argparse. After the subcommand split:
      * ``build_peripheral_so`` is called with ``clean=True`` (the existing
        driver-side clean lives inside that helper).
      * ``run_gateware_build`` is NOT called (driver-only half).
      * No ``subprocess.run`` argv references ``rm -rf src/gateware/build``.
      * The gateware sentinel file survives on disk.
    """
    pd = _make_peripheral_dir(tmp_path)
    gw_sentinel = pd / "src" / "gateware" / "build" / "SENTINEL_GATEWARE"
    driver_sentinel = pd / "build" / "aarch64" / "SENTINEL_DRIVER"
    assert gw_sentinel.exists() and driver_sentinel.exists()

    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    parser = _build_root_parser(peripherals)
    args = parser.parse_args(["peripherals", "build", "driver", "--clean", str(pd)])
    assert getattr(args, "half", None) == "driver"
    assert getattr(args, "clean", False) is True
    args.uri = None
    if not hasattr(args, "package"):
        args.package = None
    peripherals.build_cmd(args)

    # Driver builder must be invoked with clean=True.
    assert len(recorders.build_so_calls) == 1, "driver builder must run under --driver"
    pos_args, kwargs = recorders.build_so_calls[0]
    saw_clean = bool(kwargs.get("clean")) or (len(pos_args) >= 4 and bool(pos_args[3]))
    assert saw_clean, (
        "build_peripheral_so must receive clean=True under --clean --driver"
    )

    # Gateware runner must not run.
    assert recorders.run_gateware_calls == [], (
        "--driver must not invoke the gateware runner"
    )

    # Gateware tree must NOT have been touched -- sentinel survives.
    assert gw_sentinel.exists(), "--clean --driver must not touch src/gateware/build/"

    flat_argv = [
        " ".join(map(str, call[0]))
        for call in recorders.subprocess_calls
        if isinstance(call[0], list)
    ]
    gateware_clean_calls = [a for a in flat_argv if "rm -rf src/gateware/build" in a]
    assert gateware_clean_calls == [], (
        "--clean --driver must NOT issue any gateware-side clean; got: "
        f"{gateware_clean_calls!r}"
    )


# --- Case F: --clean --gateware cleans only the gateware tree --------------


def test_case_F_clean_gateware_does_not_touch_driver_tree(
    peripherals, tmp_path, monkeypatch
):
    """F: ``--clean --gateware`` -> gateware clean fires, driver sentinel survives."""
    pd = _make_peripheral_dir(tmp_path)
    driver_sentinel = pd / "build" / "aarch64" / "SENTINEL_DRIVER"
    gw_sentinel = pd / "src" / "gateware" / "build" / "SENTINEL_GATEWARE"
    assert driver_sentinel.exists() and gw_sentinel.exists()

    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.build_cmd(_build_args(pd, half="gateware", clean=True))

    # Driver tree must not be touched.
    assert driver_sentinel.exists(), "--clean --gateware must not touch build/aarch64/"

    flat_argv = [
        " ".join(map(str, call[0]))
        for call in recorders.subprocess_calls
        if isinstance(call[0], list)
    ]
    # The driver-side clean lives in build_peripheral_so (which we stubbed),
    # so the recorded subprocess.run calls should not include a driver
    # `rm -rf build/` invocation. The driver builder being uninvoked is
    # already verified by build_so_calls == []; this is the belt.
    driver_clean_calls = [
        a
        for a in flat_argv
        if "rm -rf build" in a and "rm -rf src/gateware/build" not in a
    ]
    assert recorders.build_so_calls == [], (
        "build_peripheral_so (which owns the driver clean) must not run "
        "under --gateware"
    )
    assert driver_clean_calls == [], (
        f"--clean --gateware must NOT issue a driver-side clean; got: "
        f"{driver_clean_calls!r}"
    )


# --- Case G: --clean (no half) cleans both ---------------------------------


def test_case_G_clean_no_half_cleans_both(peripherals, tmp_path, monkeypatch):
    """G: ``--clean`` alone (no half flag) -> both halves' cleans fire."""
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.build_cmd(_build_args(pd, half="both", clean=True))

    # Driver builder must be invoked with clean=True (today's clean
    # lives inside build_peripheral_so).
    assert len(recorders.build_so_calls) == 1
    _, kwargs = recorders.build_so_calls[0]
    pos_args, _ = recorders.build_so_calls[0]
    # clean=True may be passed positionally or as a kwarg; check both.
    saw_clean = bool(kwargs.get("clean")) or (len(pos_args) >= 4 and bool(pos_args[3]))
    assert saw_clean, (
        "build_peripheral_so must receive clean=True under --clean (both halves)"
    )

    # The gateware-side clean must also fire — recorded as a subprocess.run
    # call containing the gateware build dir path.
    flat_argv = [
        " ".join(map(str, call[0]))
        for call in recorders.subprocess_calls
        if isinstance(call[0], list)
    ]
    gateware_clean_calls = [a for a in flat_argv if "rm -rf src/gateware/build" in a]
    assert len(gateware_clean_calls) >= 1, (
        f"--clean (no half) must issue a gateware-side clean; got: {flat_argv!r}"
    )


# --- Case H: no --clean, no half -> nothing cleaned ------------------------


def test_case_H_no_clean_no_half_cleans_nothing(peripherals, tmp_path, monkeypatch):
    """H: ``peripherals build`` (no flags) -> neither half is cleaned.

    Both sentinels survive. The driver builder is invoked with clean=False;
    the gateware-side cleaner subprocess.run is not invoked.
    """
    pd = _make_peripheral_dir(tmp_path)
    driver_sentinel = pd / "build" / "aarch64" / "SENTINEL_DRIVER"
    gw_sentinel = pd / "src" / "gateware" / "build" / "SENTINEL_GATEWARE"

    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.build_cmd(_build_args(pd, half="both", clean=False))

    assert driver_sentinel.exists() and gw_sentinel.exists()

    # build_peripheral_so must NOT receive clean=True.
    assert len(recorders.build_so_calls) == 1
    pos_args, kwargs = recorders.build_so_calls[0]
    saw_clean = bool(kwargs.get("clean")) or (len(pos_args) >= 4 and bool(pos_args[3]))
    assert not saw_clean, (
        "build_peripheral_so must NOT receive clean=True when --clean is absent"
    )

    flat_argv = [
        " ".join(map(str, call[0]))
        for call in recorders.subprocess_calls
        if isinstance(call[0], list)
    ]
    gateware_clean_calls = [a for a in flat_argv if "rm -rf src/gateware/build" in a]
    assert gateware_clean_calls == [], (
        f"no --clean flag must issue zero gateware-side cleans; got: {flat_argv!r}"
    )


# ===========================================================================
# AC-8: peripherals deploy flag handling
# ===========================================================================


# --- Case I: deploy --driver -u <uri> --------------------------------------


def test_case_I_deploy_driver_only(peripherals, tmp_path, monkeypatch):
    """I: ``peripherals deploy driver -u <uri>`` -> driver-only build then deploy.

    Parses via argparse: the ``driver`` subcommand under ``deploy`` must set
    ``args.half`` to ``"driver"``.
    """
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    parser = _build_root_parser(peripherals)
    args = parser.parse_args(["peripherals", "deploy", "driver", str(pd)])
    assert getattr(args, "half", None) == "driver", (
        f"args.half must be 'driver' after the 'driver' subcommand on deploy; got: "
        f"{getattr(args, 'half', None)!r}"
    )
    args.uri = "10.0.0.1"
    if not hasattr(args, "package"):
        args.package = None
    peripherals.deploy_cmd(args)

    assert len(recorders.build_so_calls) == 1
    assert recorders.run_gateware_calls == [], (
        "--driver deploy must not invoke the gateware runner"
    )
    assert len(recorders.deploy_calls) == 1, "deploy_package must be invoked once"
    uri, deb_path = recorders.deploy_calls[0]
    assert uri == "10.0.0.1"
    assert deb_path.endswith(".deb")


# --- Case J: deploy --gateware -u <uri> ------------------------------------


def test_case_J_deploy_gateware_only(peripherals, tmp_path, monkeypatch):
    """J: ``peripherals deploy --gateware -u <uri>`` -> gateware-only build then deploy."""
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.deploy_cmd(_deploy_args(pd, half="gateware", uri="10.0.0.1"))

    assert recorders.build_so_calls == [], (
        "--gateware deploy must not invoke the driver builder"
    )
    assert len(recorders.run_gateware_calls) == 1
    assert len(recorders.deploy_calls) == 1
    uri, deb_path = recorders.deploy_calls[0]
    assert uri == "10.0.0.1"


# --- Case K: deploy with an invalid target -> argparse rejects -------------


def test_case_K_deploy_invalid_target_is_invalid_choice_error(
    peripherals, tmp_path, capsys
):
    """K: ``deploy <bogus>`` -> argparse `SystemExit(2)` + "invalid choice".

    Mirror of case D for ``deploy``: the half selectors are subcommands, so
    the old ``--driver --gateware`` mutex is impossible. Only
    ``driver`` / ``gateware`` / ``both`` are accepted targets.
    """
    parser = _build_root_parser(peripherals)
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["peripherals", "deploy", "neither"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    err = captured.err.lower()
    assert "invalid choice" in err, (
        f"stderr must reference argparse's 'invalid choice'; got: {captured.err!r}"
    )
    assert "driver" in err and "gateware" in err and "both" in err


# --- Case L: deploy --package <path>.deb --gateware -u <uri> ---------------


def test_case_L_deploy_package_short_circuit_ignores_half_flag(
    peripherals, tmp_path, monkeypatch, capsys
):
    """L: ``--package`` short-circuits; the ``--gateware`` flag is acknowledged
    but does not redirect the .deb path. A warning naming both flags is
    emitted to stdout (rich console)."""
    pd = _make_peripheral_dir(tmp_path)
    # Pre-build a fake .deb at a path the test will supply via --package.
    fake_deb = tmp_path / "prebuilt.deb"
    fake_deb.write_text("dpkg-stub")

    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.deploy_cmd(
        _deploy_args(pd, half="gateware", uri="10.0.0.1", package=str(fake_deb))
    )

    # deploy_package called once with the user-supplied .deb path.
    assert len(recorders.deploy_calls) == 1
    uri, deb_path = recorders.deploy_calls[0]
    assert uri == "10.0.0.1"
    assert os.path.abspath(deb_path) == os.path.abspath(str(fake_deb))

    # No build paths invoked.
    assert recorders.build_so_calls == []
    assert recorders.run_gateware_calls == []

    # The warning must mention `--gateware` (and reference `--package` or the
    # fact that the half-selector is being ignored).
    captured = capsys.readouterr()
    out_lower = (captured.out + captured.err).lower()
    assert "--gateware" in out_lower or "gateware" in out_lower
    assert (
        "ignore" in out_lower or "--package" in out_lower or "package" in out_lower
    ), (
        "the --package short-circuit must emit a warning that the half-selector "
        f"is being ignored; got: {captured.out + captured.err!r}"
    )


# ===========================================================================
# Two-deb staging layout (driver deb + -gateware deb)
# ===========================================================================


# These cases run the REAL packagers under a fake fpm stub so the staging
# layout written to disk can be asserted on directly.


def _captured_staging_files(staging_dir):
    """Walk ``staging_dir`` and return a sorted list of relative file paths."""
    out: list[str] = []
    for root, _, files in os.walk(staging_dir):
        rel_root = os.path.relpath(root, staging_dir)
        for f in files:
            out.append(os.path.normpath(os.path.join(rel_root, f)))
    return sorted(out)


def _seed_runtime_libs_under(peripheral_dir):
    """Pre-populate libscifi-peripheral-sdk.so* artifacts so the driver-half
    extraction step has something to copy into the staging dir.

    AC-12 says ``build_peripheral_deb`` extracts the runtime libs from the
    driver Docker image. The implementer is free to either run the real docker
    cp under stubs or to look for already-extracted .so files on disk. To
    keep the test agnostic to which path the implementation picks, we drop
    the libs directly under build/aarch64/ where the driver builder would
    normally place them.
    """
    libs_dir = os.path.join(str(peripheral_dir), "build", "aarch64")
    os.makedirs(libs_dir, exist_ok=True)
    for fname in (
        "libscifi-peripheral-sdk.so",
        "libscifi-peripheral-sdk.so.0",
        "libscifi-peripheral-sdk.so.0.1.0",
    ):
        p = os.path.join(libs_dir, fname)
        with open(p, "w") as fh:
            fh.write("fake-runtime-lib")


def test_case_M_both_emits_driver_deb_and_gateware_deb(
    peripherals, tmp_path, monkeypatch
):
    """M: ``build both`` stages a driver-only deb AND a separate gateware deb."""
    pd = _make_peripheral_dir(tmp_path)
    _seed_runtime_libs_under(pd)
    fake_bit = tmp_path / "fake.bit"
    fake_bit.write_text("BITSTREAM")

    staging_dirs: list = []
    real_mkdtemp = peripherals.tempfile.mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        staging_dirs.append(d)
        return d

    # Capture the real packagers BEFORE the common stubs replace them.
    real_driver_deb = peripherals.build_peripheral_deb
    real_gateware_deb = peripherals.build_gateware_deb
    monkeypatch.setattr(peripherals.tempfile, "mkdtemp", spy_mkdtemp)
    _install_common_stubs(peripherals, monkeypatch, tmp_path, fake_bit=fake_bit)
    monkeypatch.setattr(peripherals, "build_peripheral_deb", real_driver_deb)
    monkeypatch.setattr(peripherals, "build_gateware_deb", real_gateware_deb)
    # Fake fpm so each packager's "did a .deb land?" verification passes.
    calls: list = []
    monkeypatch.setattr(
        peripherals.subprocess,
        "run",
        fake_fpm_run(os.path.join(str(pd), "dist"), calls),
    )

    peripherals.build_cmd(_build_args(pd, half="both"))

    assert len(staging_dirs) == 2, (
        f"one staging dir per deb (driver, then gateware); got {staging_dirs!r}"
    )
    driver_files = _captured_staging_files(staging_dirs[0])
    gateware_files = _captured_staging_files(staging_dirs[1])

    assert any(
        f.endswith(os.path.join("usr/lib/scifi/plugins", "intan_rhd2132.so"))
        for f in driver_files
    ), f"driver deb stages the .so; got: {driver_files!r}"
    assert any("libscifi-peripheral-sdk" in f for f in driver_files), (
        f"driver deb carries the SDK runtime; got: {driver_files!r}"
    )
    assert not any(f.endswith(".bit") for f in driver_files), (
        f"driver deb must not carry the bitstream; got: {driver_files!r}"
    )

    assert any(
        f.endswith(os.path.join("opt/scifi/bitstreams/custom", "intan_rhd2132.bit"))
        for f in gateware_files
    ), f"gateware deb stages the bit under custom/; got: {gateware_files!r}"
    assert any(
        f.endswith(
            os.path.join("opt/scifi/bitstreams/custom", "intan_rhd2132.manifest.json")
        )
        for f in gateware_files
    ), f"gateware deb stages the manifest fragment; got: {gateware_files!r}"
    assert not any(f.endswith(".so") for f in gateware_files), (
        f"gateware deb must not carry any .so; got: {gateware_files!r}"
    )

    # Both fpm invocations happened, with distinct package names.
    fpm_names = []
    for c in calls:
        if "fpm" in c:
            fpm_argv = c[c.index("fpm"):]
            fpm_names.append(fpm_argv[fpm_argv.index("-n") + 1])
    assert fpm_names == ["intan_rhd2132", "intan_rhd2132-gateware"]


def test_case_N_driver_deb_fpm_input_excludes_postinstall(
    peripherals, tmp_path, monkeypatch
):
    """N: the driver deb's fpm input is ``usr`` — /postinstall.sh must not ship
    as payload (it would dpkg-conflict with the gateware deb's)."""
    pd = _make_peripheral_dir(tmp_path)
    _seed_runtime_libs_under(pd)

    real_driver_deb = peripherals.build_peripheral_deb
    _install_common_stubs(peripherals, monkeypatch, tmp_path)
    monkeypatch.setattr(peripherals, "build_peripheral_deb", real_driver_deb)
    calls: list = []
    monkeypatch.setattr(
        peripherals.subprocess,
        "run",
        fake_fpm_run(os.path.join(str(pd), "dist"), calls),
    )

    peripherals.build_cmd(_build_args(pd, half="driver"))

    fpm_call = next(c for c in calls if "fpm" in c)
    assert fpm_call[-1] == "usr", (
        f"driver fpm input must be 'usr' so postinstall.sh isn't payload; "
        f"got: {fpm_call!r}"
    )
    # postinstall.sh is still wired as the maintainer script.
    assert fpm_call[fpm_call.index("--after-install") + 1] == "/pkg/postinstall.sh"


def test_case_O_gateware_only_build_emits_only_gateware_deb(
    peripherals, tmp_path, monkeypatch
):
    """O: ``build gateware`` stages ONLY the gateware deb (bit + fragment)."""
    pd = _make_peripheral_dir(tmp_path)
    _seed_runtime_libs_under(pd)
    fake_bit = tmp_path / "fake.bit"
    fake_bit.write_text("BITSTREAM")

    staging_dirs: list = []
    real_mkdtemp = peripherals.tempfile.mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        staging_dirs.append(d)
        return d

    real_gateware_deb = peripherals.build_gateware_deb
    monkeypatch.setattr(peripherals.tempfile, "mkdtemp", spy_mkdtemp)
    _install_common_stubs(peripherals, monkeypatch, tmp_path, fake_bit=fake_bit)
    monkeypatch.setattr(peripherals, "build_gateware_deb", real_gateware_deb)
    calls: list = []
    monkeypatch.setattr(
        peripherals.subprocess,
        "run",
        fake_fpm_run(os.path.join(str(pd), "dist"), calls),
    )

    peripherals.build_cmd(_build_args(pd, half="gateware"))

    assert len(staging_dirs) == 1
    files = _captured_staging_files(staging_dirs[0])
    assert any(
        f.endswith(os.path.join("opt/scifi/bitstreams/custom", "intan_rhd2132.bit"))
        for f in files
    ), f"gateware deb stages the bit; got: {files!r}"
    with open(
        os.path.join(
            staging_dirs[0],
            "opt", "scifi", "bitstreams", "custom", "intan_rhd2132.manifest.json",
        ),
        "r",
        encoding="utf-8",
    ) as fh:
        frag = json.load(fh)
    assert frag == {
        "name": "gateware",
        "usb_pid": 4,
        "artifact": "custom/intan_rhd2132.bit",
    }
    assert not any(f.endswith(".so") for f in files)
    assert not any("libscifi-peripheral-sdk" in f for f in files)


# ===========================================================================
# Two-deb deploy + summary error path
# ===========================================================================


def test_case_Q_deploy_both_streams_two_debs(peripherals, tmp_path, monkeypatch):
    """Q: ``deploy both`` makes two DeployApp calls — driver deb first.

    _build_debs anchors the find_deb_package lookup on ``<name>_<version>``
    (not just ``<name>``) so stale debs accumulated in dist/ across version
    bumps can never shadow the freshly built one.  The fixture manifest version
    is "0.1.0", so both paths must carry that version component.
    """
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    peripherals.deploy_cmd(_deploy_args(pd, half="both", uri="10.0.0.1"))

    assert len(recorders.deploy_calls) == 2, "one DeployApp stream per deb"
    uris = [u for u, _ in recorders.deploy_calls]
    paths = [p for _, p in recorders.deploy_calls]
    assert uris == ["10.0.0.1", "10.0.0.1"]
    assert paths[0].endswith("intan_rhd2132_0.1.0_arm64.deb")
    assert paths[1].endswith("intan_rhd2132-gateware_0.1.0_arm64.deb")


def test_case_Q2_deploy_stops_after_failed_driver_deploy(
    peripherals, tmp_path, monkeypatch, capsys
):
    """Q2: if the driver deb deploy fails, the gateware deb is NOT streamed."""
    pd = _make_peripheral_dir(tmp_path)
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    def failing_deploy(uri, deb_path):
        recorders.deploy_calls.append((uri, deb_path))
        return False

    monkeypatch.setattr(peripherals, "deploy_package", failing_deploy)

    peripherals.deploy_cmd(_deploy_args(pd, half="both", uri="10.0.0.1"))

    assert len(recorders.deploy_calls) == 1, (
        "gateware deb must not stream after the driver deploy failed"
    )
    assert "deploy failed" in capsys.readouterr().out.lower()


def test_case_R_gateware_build_aborts_without_usb_pid(
    peripherals, tmp_path, monkeypatch, capsys
):
    """R: a bitstream with no .summary.json aborts BEFORE deb staging."""
    pd = _make_peripheral_dir(tmp_path)
    # Bit WITHOUT a sibling summary: bypass the harness's summary-writing stub.
    bare_bit = tmp_path / "bare.bit"
    bare_bit.write_text("bit")
    recorders = _install_common_stubs(peripherals, monkeypatch, tmp_path)

    def fake_run_gateware_no_summary(*args, **kwargs):
        recorders.run_gateware_calls.append((args, kwargs))
        return str(bare_bit)

    gateware_mod = importlib.import_module("synapse.cli.gateware")
    monkeypatch.setattr(
        gateware_mod, "run_gateware_build", fake_run_gateware_no_summary
    )
    monkeypatch.setattr(
        peripherals.gateware, "run_gateware_build", fake_run_gateware_no_summary
    )

    peripherals.build_cmd(_build_args(pd, half="gateware"))

    assert recorders.build_gateware_deb_calls == [], (
        "no gateware deb staging without a usb_pid"
    )
    out = capsys.readouterr().out.lower()
    assert "summary" in out


