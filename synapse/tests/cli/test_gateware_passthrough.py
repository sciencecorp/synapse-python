"""AC-14 → AC-13 (sub-phase 4.6).

Tests the ``synapsectl peripherals gateware <verb> [args...]`` pass-through
dispatcher introduced by AC-13. The dispatcher MUST forward argv verbatim
to ``axon-peripheral-sdk`` inside the gateware container with NO
synapsectl-side argv parsing, NO shell concatenation, and NO
``shlex.quote``-style escaping.

Per AC-13 the dispatcher's top-level handler sequence is::

    license_mode = build_license_docker_args(os.environ)
    peripheral_dir = Path(os.getcwd())
    if not (peripheral_dir / "Dockerfiles" / "gateware.Dockerfile").exists():
        sys.exit(...)
    gateware_image_tag = build_docker_image(str(peripheral_dir))["gateware"]
    sys.exit(_gateware_passthrough(args.argv, peripheral_dir, license_mode,
                                   gateware_image_tag))

so the handler ALWAYS terminates via ``sys.exit`` -- tests wrap each
invocation in ``pytest.raises(SystemExit)``.

Mocking strategy:
  * ``synapse.cli.peripherals.subprocess.run`` -> recorder returning
    ``CompletedProcess(returncode=0)``.
  * ``synapse.cli.peripherals.build_docker_image`` -> returns
    ``{"gateware": "fake-gw:latest-amd64"}``.
  * ``os.getuid`` / ``os.getgid`` -> patched at the ``synapse.cli.peripherals.os``
    name so the ``--user`` argv element is deterministic.
  * ``os.getcwd`` -> patched so the dispatcher sees a tmp-path peripheral
    directory containing ``Dockerfiles/gateware.Dockerfile``.
  * ``LM_LICENSE_FILE`` -> set / unset via ``monkeypatch.setenv`` /
    ``monkeypatch.delenv``.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def peripherals():
    """Lazy-import ``synapse.cli.peripherals``.

    Deferring the import lets a per-test ImportError surface as a clean
    failure instead of a collection crash.
    """
    return importlib.import_module("synapse.cli.peripherals")


@pytest.fixture()
def gateware_mod():
    return importlib.import_module("synapse.cli.gateware")


def _build_root_parser(peripherals):
    """Build a fresh root parser wired with ``peripherals.add_commands``.

    Mirrors what ``synapse.cli.__main__`` does at runtime, but without
    triggering the broken transitive import of ``synapse.cli.settings``
    (the conftest stubs both).
    """
    parser = argparse.ArgumentParser(prog="synapsectl")
    subparsers = parser.add_subparsers(dest="cmd")
    peripherals.add_commands(subparsers)
    return parser


def _make_peripheral_dir(tmp_path):
    """Create a tmp peripheral dir with Dockerfiles/gateware.Dockerfile.

    Returns the absolute path string of the dir; the dispatcher's
    cwd-based check looks for ``Dockerfiles/gateware.Dockerfile`` under
    this directory.
    """
    pd = tmp_path / "fake-peripheral"
    pd.mkdir()
    (pd / "Dockerfiles").mkdir()
    (pd / "Dockerfiles" / "gateware.Dockerfile").write_text(
        "FROM ubuntu:22.04\nARG HOST_UID=1000\n"
    )
    return pd


def _make_license_file(tmp_path):
    """Create a tmp license file and return its realpath."""
    lic = tmp_path / "license.dat"
    lic.write_text("FAKE LATTICE LICENSE\n")
    return str(lic.resolve())


def _install_dispatcher_stubs(
    peripherals,
    monkeypatch,
    tmp_path,
    *,
    license_value,
    uid=1234,
    gid=5678,
    getuid_raises=None,
):
    """Install stubs for the AC-13 dispatcher path and return a recorder.

    ``license_value`` may be:
      * a string -> ``LM_LICENSE_FILE`` is set to that value
      * ``None`` -> ``LM_LICENSE_FILE`` is deleted from os.environ

    ``getuid_raises``: if not None, ``os.getuid`` is stubbed to raise this
    exception instance/class (used to model Python-on-Windows).
    """
    recorder = SimpleNamespace(calls=[])

    def fake_run(argv, *args, **kwargs):
        recorder.calls.append((argv, args, dict(kwargs)))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    # subprocess.run -> recorder. Patched on the module under test so we
    # capture the dispatcher's exact argv-list.
    monkeypatch.setattr(peripherals.subprocess, "run", fake_run)

    # build_docker_image -> fixed dict so the dispatcher gets a known tag.
    monkeypatch.setattr(
        peripherals,
        "build_docker_image",
        lambda *a, **kw: {
            "driver": "fake-driver:latest-amd64",
            "gateware": "fake-gw:latest-amd64",
        },
    )

    # os.getcwd -> the fake peripheral dir.
    pd = _make_peripheral_dir(tmp_path)
    monkeypatch.setattr(peripherals.os, "getcwd", lambda: str(pd))

    # os.getuid / os.getgid on the peripherals module.
    if getuid_raises is not None:

        def _raises(*_a, **_kw):
            raise getuid_raises

        monkeypatch.setattr(peripherals.os, "getuid", _raises)
    else:
        monkeypatch.setattr(peripherals.os, "getuid", lambda: uid)
    monkeypatch.setattr(peripherals.os, "getgid", lambda: gid)

    # LM_LICENSE_FILE.
    if license_value is None:
        monkeypatch.delenv("LM_LICENSE_FILE", raising=False)
    else:
        monkeypatch.setenv("LM_LICENSE_FILE", license_value)

    return recorder, pd


def _dispatch(peripherals, argv_tail):
    """Drive the ``gateware`` subcommand via the real argparse surface.

    ``argv_tail`` is the list AFTER ``peripherals gateware``, e.g.
    ``["doctor"]`` or ``["validate", "--project", "src/gateware"]``.

    The dispatcher handler always ends in ``sys.exit``; the caller is
    responsible for wrapping in ``pytest.raises(SystemExit)``.
    """
    parser = _build_root_parser(peripherals)
    args = parser.parse_args(["peripherals", "gateware", *argv_tail])
    args.func(args)


def _docker_argv(call):
    """Return the docker-run argv list from a recorded subprocess.run call."""
    argv, _pos, _kw = call
    assert isinstance(argv, list), (
        f"subprocess.run must receive a Python list (argv form), not a string; "
        f"got: {argv!r}"
    )
    return argv


def _tail_after_image_tag(argv, image_tag):
    """Return the argv slice AFTER the gateware image tag (inclusive of
    ``axon-peripheral-sdk`` onward).
    """
    assert image_tag in argv, (
        f"image tag {image_tag!r} not present in docker argv: {argv!r}"
    )
    idx = argv.index(image_tag)
    return argv[idx + 1 :]


# ---------------------------------------------------------------------------
# AC-14 case 1: no-arg verb forwarded verbatim
# ---------------------------------------------------------------------------


def test_case_1_no_arg_verb_doctor_forwarded_verbatim(
    peripherals, tmp_path, monkeypatch
):
    """1: ``gateware doctor`` -> argv tail is exactly
    ``["axon-peripheral-sdk", "doctor"]``."""
    lic = _make_license_file(tmp_path)
    recorder, _pd = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit) as excinfo:
        _dispatch(peripherals, ["doctor"])

    assert excinfo.value.code == 0
    assert len(recorder.calls) == 1, (
        f"exactly one docker-run subprocess call expected; got: {recorder.calls!r}"
    )
    argv = _docker_argv(recorder.calls[0])
    tail = _tail_after_image_tag(argv, "fake-gw:latest-amd64")
    assert tail == ["axon-peripheral-sdk", "doctor"], (
        f"no-arg verb must be forwarded verbatim; got tail: {tail!r}"
    )

    # shell=False (the default) -- explicit check that nobody set shell=True.
    _argv, _pos, kw = recorder.calls[0]
    assert kw.get("shell", False) is False, (
        f"subprocess.run must be invoked with shell=False; got kwargs: {kw!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 2: long flag with value forwarded verbatim
# ---------------------------------------------------------------------------


def test_case_2_long_flag_value_validate_forwarded_verbatim(
    peripherals, tmp_path, monkeypatch
):
    """2: ``gateware validate --project src/gateware`` -> tail is exactly
    ``["axon-peripheral-sdk", "validate", "--project", "src/gateware"]``."""
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["validate", "--project", "src/gateware"])

    assert len(recorder.calls) == 1
    argv = _docker_argv(recorder.calls[0])
    tail = _tail_after_image_tag(argv, "fake-gw:latest-amd64")
    assert tail == [
        "axon-peripheral-sdk",
        "validate",
        "--project",
        "src/gateware",
    ], f"long-flag verb must be forwarded byte-for-byte; got tail: {tail!r}"


# ---------------------------------------------------------------------------
# AC-14 case 3: short flag with exotic value (contains '::')
# ---------------------------------------------------------------------------


def test_case_3_short_flag_with_double_colon_preserved(
    peripherals, tmp_path, monkeypatch
):
    """3: ``gateware sim -k some::test_id`` -> the ``::`` is preserved
    byte-for-byte in argv form.

    Under shell-string concatenation the ``::`` might survive too, but a
    naive ``shlex.quote(arg)`` wrapper would inject single-quotes around
    the value. Argv-list form makes quoting unnecessary; this test locks
    that contract in so a future maintainer can't slip a quote-helper in.
    """
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["sim", "-k", "some::test_id"])

    assert len(recorder.calls) == 1
    argv = _docker_argv(recorder.calls[0])
    tail = _tail_after_image_tag(argv, "fake-gw:latest-amd64")
    assert tail == ["axon-peripheral-sdk", "sim", "-k", "some::test_id"], (
        f"short-flag-with-exotic-value must be preserved verbatim; got tail: {tail!r}"
    )
    # Belt-and-suspenders: no element in argv should equal a quote-wrapped
    # version of the exotic value.
    assert "'some::test_id'" not in argv, (
        f"docker argv must not shell-quote the exotic value; got: {argv!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 4: --user matches patched getuid()/getgid()
# ---------------------------------------------------------------------------


def test_case_4_user_flag_matches_patched_uid_gid(peripherals, tmp_path, monkeypatch):
    """4: ``--user <uid>:<gid>`` is built from os.getuid()/os.getgid()."""
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic, uid=4242, gid=8484
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor"])

    argv = _docker_argv(recorder.calls[0])
    assert "--user" in argv, f"--user flag missing; got: {argv!r}"
    user_idx = argv.index("--user")
    assert argv[user_idx + 1] == "4242:8484", (
        f"--user value must be 'uid:gid' from patched getuid/getgid; "
        f"got: {argv[user_idx + 1]!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 5: -v <peripheral_dir>:/home/workspace bind-mount
# ---------------------------------------------------------------------------


def test_case_5_bind_mount_is_peripheral_dir_abspath(
    peripherals, tmp_path, monkeypatch
):
    """5: ``-v <abspath(peripheral_dir)>:/home/workspace`` is present."""
    lic = _make_license_file(tmp_path)
    recorder, pd = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor"])

    argv = _docker_argv(recorder.calls[0])
    expected_mount = f"{os.path.abspath(str(pd))}:/home/workspace"
    assert expected_mount in argv, (
        f"docker argv must include workspace bind-mount {expected_mount!r}; "
        f"got: {argv!r}"
    )
    # The element immediately before the mount-spec must be a `-v`.
    mount_idx = argv.index(expected_mount)
    assert argv[mount_idx - 1] == "-v", (
        f"bind-mount must be introduced by '-v'; got argv[{mount_idx - 1}]: "
        f"{argv[mount_idx - 1]!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 6: -w /home/workspace working dir
# ---------------------------------------------------------------------------


def test_case_6_working_dir_is_home_workspace(peripherals, tmp_path, monkeypatch):
    """6: ``-w /home/workspace`` is present in the docker argv."""
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor"])

    argv = _docker_argv(recorder.calls[0])
    assert "-w" in argv, f"-w flag missing; got: {argv!r}"
    w_idx = argv.index("-w")
    assert argv[w_idx + 1] == "/home/workspace", (
        f"-w value must be '/home/workspace'; got: {argv[w_idx + 1]!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 7: subprocess.run called with a list, shell=False
# ---------------------------------------------------------------------------


def test_case_7_subprocess_run_is_argv_list_no_shell(
    peripherals, tmp_path, monkeypatch
):
    """7: ``subprocess.run`` first arg is a list; ``shell`` is not True."""
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor"])

    assert len(recorder.calls) == 1
    argv, _pos, kwargs = recorder.calls[0]
    assert isinstance(argv, list), (
        f"subprocess.run first arg must be a list (argv form), not a string; "
        f"got type: {type(argv).__name__} value: {argv!r}"
    )
    assert kwargs.get("shell", False) is False, (
        f"subprocess.run must be called with shell=False (default); "
        f"got kwargs: {kwargs!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 8: floating LM_LICENSE_FILE (port@host) -> -e only, no -v
# ---------------------------------------------------------------------------


def test_case_8_floating_license_emits_env_no_bind(peripherals, tmp_path, monkeypatch):
    """8: ``LM_LICENSE_FILE=27000@licenseserver`` -> only ``-e`` is added.

    No license-file ``-v`` bind-mount; the env var is forwarded as-is.
    """
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value="27000@licenseserver"
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor"])

    argv = _docker_argv(recorder.calls[0])
    assert "LM_LICENSE_FILE=27000@licenseserver" in argv, (
        f"floating-license env var must be forwarded verbatim; got: {argv!r}"
    )
    env_idx = argv.index("LM_LICENSE_FILE=27000@licenseserver")
    assert argv[env_idx - 1] == "-e", (
        f"floating-license must be introduced by '-e'; got argv[{env_idx - 1}]: "
        f"{argv[env_idx - 1]!r}"
    )
    # ZERO license-bind-mounts: no `-v` element should target the in-container
    # license path.
    license_binds = [
        a for a in argv if isinstance(a, str) and "/opt/lattice/license.dat" in a
    ]
    assert license_binds == [], (
        f"floating-license mode must not emit a license bind-mount; got: {license_binds!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 9: file-path LM_LICENSE_FILE -> -v + -e pair
# ---------------------------------------------------------------------------


def test_case_9_file_path_license_emits_bind_and_env(
    peripherals, tmp_path, monkeypatch
):
    """9: ``LM_LICENSE_FILE=<existing file>`` -> ``-v <real>:/opt/lattice/license.dat:ro``
    AND ``-e LM_LICENSE_FILE=/opt/lattice/license.dat``."""
    lic = _make_license_file(tmp_path)  # real on-disk file
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor"])

    argv = _docker_argv(recorder.calls[0])
    expected_bind = f"{lic}:/opt/lattice/license.dat:ro"
    assert expected_bind in argv, (
        f"file-path license must bind-mount as {expected_bind!r}; got: {argv!r}"
    )
    bind_idx = argv.index(expected_bind)
    assert argv[bind_idx - 1] == "-v", (
        f"license bind-mount must be introduced by '-v'; got argv[{bind_idx - 1}]: "
        f"{argv[bind_idx - 1]!r}"
    )
    # Env var pointing at the in-container path.
    assert "LM_LICENSE_FILE=/opt/lattice/license.dat" in argv, (
        f"file-path license must forward in-container env var; got: {argv!r}"
    )
    env_idx = argv.index("LM_LICENSE_FILE=/opt/lattice/license.dat")
    assert argv[env_idx - 1] == "-e", (
        f"in-container license env var must be introduced by '-e'; "
        f"got argv[{env_idx - 1}]: {argv[env_idx - 1]!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 10: LM_LICENSE_FILE unset -> LicenseUnsetError, no subprocess.run
# ---------------------------------------------------------------------------


def test_case_10_unset_license_does_not_invoke_subprocess(
    peripherals, gateware_mod, tmp_path, monkeypatch, capsys
):
    """10: ``LM_LICENSE_FILE`` unset -> dispatcher raises
    ``LicenseUnsetError`` (or wraps it in SystemExit) AND subprocess.run is
    never called.

    AC-13's call sequence shows ``build_license_docker_args(os.environ)``
    runs BEFORE any docker invocation; an unset license must therefore
    short-circuit the dispatcher before subprocess.run is touched.

    Strengthening: this case has to reach the LICENSE branch, not the
    argparse-invalid-choice branch (which would also raise SystemExit(2)
    today because the `gateware` subcommand isn't registered yet). We
    assert the error message mentions ``LM_LICENSE_FILE`` and does NOT
    contain argparse's ``invalid choice`` text, proving the dispatcher
    actually reached the license-resolution step.
    """
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=None
    )

    with pytest.raises((SystemExit, gateware_mod.LicenseUnsetError)) as excinfo:
        _dispatch(peripherals, ["doctor"])

    # If the dispatcher chose to wrap in SystemExit, the exit code must be
    # non-zero; raw LicenseUnsetError is also acceptable.
    if isinstance(excinfo.value, SystemExit):
        assert excinfo.value.code not in (0, None), (
            f"unset license must exit non-zero; got code: {excinfo.value.code!r}"
        )

    assert recorder.calls == [], (
        f"subprocess.run must NOT be invoked when LM_LICENSE_FILE is unset; "
        f"got: {recorder.calls!r}"
    )

    # Anti-tautology: the error must come from the LICENSE branch, not
    # argparse's invalid-choice path. argparse would emit "invalid choice"
    # to stderr and never touch the license-resolution code.
    captured = capsys.readouterr()
    msg = (captured.out + captured.err + str(excinfo.value)).lower()
    assert "invalid choice" not in msg, (
        f"case 10 must reach the license-resolution branch, NOT argparse's "
        f"invalid-choice path (which fires today because `gateware` is not "
        f"yet a registered subcommand). The presence of 'invalid choice' "
        f"means AC-13's subparser registration hasn't happened yet. "
        f"got: {captured.out + captured.err!r} value={excinfo.value!r}"
    )
    assert "lm_license_file" in msg, (
        f"unset-license error must mention 'LM_LICENSE_FILE' so users know "
        f"what env var to set; got: {captured.out + captured.err!r} "
        f"value={excinfo.value!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 11: `gateware --help` consumed by argparse, no subprocess.run
# ---------------------------------------------------------------------------


def test_case_11_gateware_help_consumed_by_argparse(
    peripherals, tmp_path, monkeypatch, capsys
):
    """11: ``peripherals gateware --help`` -> argparse exits 0, prints
    synapsectl-side gateware help; subprocess.run NOT called.

    AC-13's `--help` dichotomy: when `--help` is the FIRST token after
    `gateware`, argparse consumes it BEFORE REMAINDER captures anything.
    """
    # Even for the --help path the dispatcher's pre-handler stubs are
    # harmless: argparse exits inside parse_args before the handler runs.
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    parser = _build_root_parser(peripherals)
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["peripherals", "gateware", "--help"])

    assert excinfo.value.code == 0, (
        f"--help must exit cleanly with code 0; got: {excinfo.value.code!r}"
    )
    assert recorder.calls == [], (
        f"--help path must not invoke subprocess.run; got: {recorder.calls!r}"
    )
    captured = capsys.readouterr()
    help_text = (captured.out + captured.err).lower()
    # The synapsectl-side gateware subcommand help should reference either
    # the verb name "gateware" or the pass-through concept.
    assert "gateware" in help_text or "pass" in help_text, (
        f"gateware --help text must mention 'gateware' or 'pass'; "
        f"got: {captured.out!r} stderr={captured.err!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 12: `gateware doctor --help` IS forwarded
# ---------------------------------------------------------------------------


def test_case_12_verb_help_is_forwarded_to_sdk(peripherals, tmp_path, monkeypatch):
    """12: ``peripherals gateware doctor --help`` -> REMAINDER captures
    BOTH tokens; subprocess.run IS called with the verb + --help in the tail.

    Companion to case 11: when at least one non-``--help`` positional
    appears first, the entire tail is REMAINDER-captured and forwarded
    untouched to ``axon-peripheral-sdk`` so the SDK shows its own
    per-verb help.
    """
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["doctor", "--help"])

    assert len(recorder.calls) == 1, (
        f"verb + --help must be forwarded (single docker call); got: {recorder.calls!r}"
    )
    argv = _docker_argv(recorder.calls[0])
    tail = _tail_after_image_tag(argv, "fake-gw:latest-amd64")
    assert tail == ["axon-peripheral-sdk", "doctor", "--help"], (
        f"verb-help tail must be forwarded verbatim; got: {tail!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 13: `peripherals --help` lists exactly {build, deploy, gateware}
# ---------------------------------------------------------------------------


def test_case_13_peripherals_help_lists_three_subcommands(peripherals, capsys):
    """13: ``peripherals --help`` lists exactly ``build``, ``deploy``,
    ``gateware`` as subcommand entries -- no hard-coded SDK verbs.

    Locks the contract that synapsectl does NOT enumerate SDK verbs at
    the argparse level; the SDK is the sole source of truth.
    """
    parser = _build_root_parser(peripherals)
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["peripherals", "--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    help_text = captured.out

    # All three required subcommands must be listed.
    assert "build" in help_text, (
        f"peripherals --help must list 'build' subcommand; got: {help_text!r}"
    )
    assert "deploy" in help_text, (
        f"peripherals --help must list 'deploy' subcommand; got: {help_text!r}"
    )
    assert "gateware" in help_text, (
        f"peripherals --help must list 'gateware' subcommand; got: {help_text!r}"
    )

    # SDK verb names that MUST NOT appear as registered subcommands. We scan
    # the help text for these names appearing as standalone tokens followed by
    # a description (the argparse subparser-list format puts the verb name
    # alone on a line or as the first token of a 2-space-indented line).
    forbidden_sdk_verbs = [
        "validate",
        "sim",
        "regenerate",
        "add-peripheral",
        "list-profiles",
    ]
    for verb in forbidden_sdk_verbs:
        # Reject only the argparse "    <verb>   <description>" subparser
        # entry shape, allowing the verb name to appear inside descriptive
        # prose (e.g. "for SDK-side help, run gateware <verb> --help").
        lines = help_text.splitlines()
        offending = [
            ln
            for ln in lines
            if ln.startswith("    " + verb + " ")
            or ln.strip() == verb
            or ln.startswith("    " + verb + "\t")
        ]
        assert offending == [], (
            f"peripherals --help must not list '{verb}' as a registered "
            f"subcommand; got lines: {offending!r}"
        )


# ---------------------------------------------------------------------------
# AC-14 case 14: `peripherals nonsense` -> argparse invalid-choice, no docker
# ---------------------------------------------------------------------------


def test_case_14_invalid_subcommand_is_argparse_error_no_subprocess(
    peripherals, tmp_path, monkeypatch, capsys
):
    """14: ``peripherals nonsense`` (NOT build/deploy/gateware) -> argparse
    ``SystemExit(2)`` with 'invalid choice' in stderr. subprocess.run NOT
    invoked.

    This is the regression test against the rejected Amendment-5
    unknown-verb fall-through design. A future maintainer who re-introduces
    blind fall-through MUST break this test.
    """
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    parser = _build_root_parser(peripherals)
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["peripherals", "nonsense"])

    assert excinfo.value.code == 2, (
        f"invalid subcommand must exit with argparse code 2; "
        f"got: {excinfo.value.code!r}"
    )
    captured = capsys.readouterr()
    err_lower = captured.err.lower()
    assert "invalid choice" in err_lower, (
        f"stderr must contain argparse's 'invalid choice' message; "
        f"got: {captured.err!r}"
    )
    # Strengthening (anti-tautology): the choice list mentioned in the
    # error must include ALL THREE registered subcommands (build, deploy,
    # gateware). Today the parser only registers {build, deploy} so the
    # error reads "(choose from 'build', 'deploy')" which would pass a
    # naive `"invalid choice" in err` check tautologically. After AC-13
    # lands, the error must reference 'gateware' alongside the other two.
    assert "gateware" in err_lower, (
        f"the invalid-choice error must list 'gateware' as a valid "
        f"subcommand (proves AC-13 registered it). Without this the "
        f"test would pass tautologically against today's parser which "
        f"only knows {{build, deploy}}. got: {captured.err!r}"
    )
    assert "build" in err_lower and "deploy" in err_lower, (
        f"the invalid-choice error must also list 'build' and 'deploy'; "
        f"got: {captured.err!r}"
    )
    # subprocess.run must NOT have been called.
    assert recorder.calls == [], (
        f"unknown subcommand must NOT trigger any subprocess.run; "
        f"got: {recorder.calls!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 15: future-verb forwarded verbatim (no known-verb gate)
# ---------------------------------------------------------------------------


def test_case_15_future_verb_forwarded_no_gate(peripherals, tmp_path, monkeypatch):
    """15: ``gateware future-verb-2027`` -> REMAINDER captures the unknown
    verb; subprocess.run IS called with the verb in the docker argv tail.

    This proves the dispatcher does NOT gate on a known-verb list -- a
    future SDK release that adds a new verb works against today's
    synapsectl without code changes.
    """
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals, monkeypatch, tmp_path, license_value=lic
    )

    with pytest.raises(SystemExit):
        _dispatch(peripherals, ["future-verb-2027"])

    assert len(recorder.calls) == 1, (
        f"future verb must be forwarded (single docker call); got: {recorder.calls!r}"
    )
    argv = _docker_argv(recorder.calls[0])
    tail = _tail_after_image_tag(argv, "fake-gw:latest-amd64")
    assert tail == ["axon-peripheral-sdk", "future-verb-2027"], (
        f"future verb must be forwarded verbatim; got tail: {tail!r}"
    )


# ---------------------------------------------------------------------------
# AC-14 case 16: POSIX-only -- os.getuid raises AttributeError -> SystemExit
# ---------------------------------------------------------------------------


def test_case_16_non_posix_host_exits_no_subprocess(
    peripherals, tmp_path, monkeypatch, capsys
):
    """16 (AC-13 POSIX-only): ``os.getuid`` raises ``AttributeError`` ->
    dispatcher exits non-zero, subprocess.run NOT called.

    Per AC-13 lines 1035-1051 of the plan and AC-14 case 11 of the plan
    body, the dispatcher takes the *strict* reading on non-POSIX hosts:
    it raises a clear error rather than silently falling back to
    1000:1000. The printed message should reference POSIX (or
    Linux/macOS) and point the user at ``axon-peripheral-sdk`` so they
    have an actionable next step.
    """
    lic = _make_license_file(tmp_path)
    recorder, _ = _install_dispatcher_stubs(
        peripherals,
        monkeypatch,
        tmp_path,
        license_value=lic,
        getuid_raises=AttributeError("module 'os' has no attribute 'getuid'"),
    )

    with pytest.raises(SystemExit) as excinfo:
        _dispatch(peripherals, ["doctor"])

    assert excinfo.value.code not in (0, None), (
        f"non-POSIX host must exit with a non-zero status; "
        f"got code: {excinfo.value.code!r}"
    )
    assert recorder.calls == [], (
        f"non-POSIX host must NOT invoke subprocess.run; got: {recorder.calls!r}"
    )

    captured = capsys.readouterr()
    msg = (captured.out + captured.err + str(excinfo.value)).lower()
    # The error should point the user at the right alternative AND mention
    # the platform limitation. We accept any of the canonical phrasings.
    assert "posix" in msg or "linux" in msg or "macos" in msg, (
        f"non-POSIX error message must mention POSIX / Linux / macOS; "
        f"got: {captured.out + captured.err!r} value={excinfo.value!r}"
    )
    assert "axon-peripheral-sdk" in msg, (
        f"non-POSIX error message must reference axon-peripheral-sdk as the "
        f"alternative invocation path; "
        f"got: {captured.out + captured.err!r} value={excinfo.value!r}"
    )
