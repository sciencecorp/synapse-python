"""AC-10 / AC-6: unit tests for run_gateware_build().

The runner lives in `synapse.cli.gateware` per the plan's File Structure
section. Signature:

    run_gateware_build(peripheral_dir: str, image_tag: str,
                       env: Mapping[str, str] = os.environ) -> str

Behavior (per AC-6):
  1. Calls build_license_docker_args(env); LicenseUnsetError propagates.
  2. Issues `docker run --rm --user dev -v <abs>:/home/workspace
     -w /home/workspace <license-args> <image_tag> /bin/bash -lc
     'axon-peripheral-sdk build --project src/gateware'`.
  3. Non-zero exit -> raises subprocess.CalledProcessError.
  4. After success, globs
     <peripheral_dir>/src/gateware/build/bitstreams/sdk_*_extracted.bit
     and returns the newest by mtime (warns on multi-match). The *extracted*
     variant is what gets flashed; the raw sdk_*.bit is ignored.
  5. Empty glob -> FileNotFoundError with message mentioning
     "sdk_*_extracted.bit".

Sub-phase 4.4 (Tester): the xfail marker is removed — these tests now run
as live AC-6 acceptance gates and must fail until the Implementer lands
``run_gateware_build``.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import time

import pytest


@pytest.fixture()
def gateware():
    """Lazy import — avoids module-collection failure before AC-5/AC-6 land."""
    return importlib.import_module("synapse.cli.gateware")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def peripheral_dir(tmp_path):
    """Create a minimal peripheral dir with src/gateware/ + a license file."""
    pd = tmp_path / "myplugin"
    (pd / "src" / "gateware").mkdir(parents=True)
    license_file = tmp_path / "license.dat"
    license_file.write_text("FEATURE radiant ...")
    return pd, license_file


def _bitstreams_dir(peripheral_dir):
    bs = os.path.join(str(peripheral_dir), "src", "gateware", "build", "bitstreams")
    os.makedirs(bs, exist_ok=True)
    return bs


# ---------------------------------------------------------------------------
# AC-10 case 10 / 13: docker-run argv shape
# ---------------------------------------------------------------------------


def test_runner_builds_docker_run_argv_with_project_flag(
    gateware, peripheral_dir, monkeypatch
):
    """Case 10/13: captured docker-run argv has the correct shape and ends
    with the exact axon-peripheral-sdk invocation (`--project src/gateware`;
    the SDK no longer accepts `--pdc`/`--impl`).
    """
    pd, license_file = peripheral_dir
    recorded: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        recorded.append(list(argv))
        # Drop a fake extracted .bit so the post-run glob succeeds.
        bs = _bitstreams_dir(pd)
        bit = os.path.join(bs, "sdk_topbuild_extracted.bit")
        with open(bit, "w") as fp:
            fp.write("bitstream")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    result = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert len(recorded) == 1, "runner should issue exactly one docker run"
    argv = recorded[0]

    # Sanity: docker run --rm
    assert argv[0:3] == ["docker", "run", "--rm"]

    # The image tag is the second-to-last block before the entrypoint.
    assert "myplugin-gateware:latest-arm64" in argv

    # Workdir is /home/workspace (case 13)
    assert "-w" in argv
    assert argv[argv.index("-w") + 1] == "/home/workspace"

    # Bind-mount the peripheral_dir abspath to /home/workspace.
    abs_pd = os.path.abspath(str(pd))
    assert "-v" in argv
    # There may be multiple -v (license + workspace); check that the
    # workspace bind-mount is present.
    v_indices = [i for i, tok in enumerate(argv) if tok == "-v"]
    bind_targets = {argv[i + 1] for i in v_indices}
    assert f"{abs_pd}:/home/workspace" in bind_targets

    # The SDK command is the final shell -lc payload.
    assert "/bin/bash" in argv
    bash_idx = argv.index("/bin/bash")
    assert argv[bash_idx + 1] == "-lc"
    sdk_cmd = argv[bash_idx + 2]
    assert sdk_cmd == "axon-peripheral-sdk build --project src/gateware"

    # And the returned path is the extracted .bit we dropped.
    assert result.endswith("sdk_topbuild_extracted.bit")


# ---------------------------------------------------------------------------
# AC-10 case 14: LM_LICENSE_FILE forwarded
# ---------------------------------------------------------------------------


def test_runner_forwards_floating_license_arg(gateware, peripheral_dir, monkeypatch):
    """Case 14: port@host floating license -> -e LM_LICENSE_FILE=<val> in argv."""
    pd, _ = peripheral_dir
    recorded: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        recorded.append(list(argv))
        bs = _bitstreams_dir(pd)
        with open(os.path.join(bs, "sdk_topbuild_extracted.bit"), "w") as fp:
            fp.write("x")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": "27000@licenseserver"},
    )

    argv = recorded[0]
    e_indices = [i for i, tok in enumerate(argv) if tok == "-e"]
    e_pairs = [argv[i + 1] for i in e_indices]
    assert "LM_LICENSE_FILE=27000@licenseserver" in e_pairs

    # And no bind-mount for the license (port@host mode is mount-free).
    v_indices = [i for i, tok in enumerate(argv) if tok == "-v"]
    bind_targets = [argv[i + 1] for i in v_indices]
    assert not any("/opt/lattice/license.dat" in t for t in bind_targets)


# ---------------------------------------------------------------------------
# AC-10 case 15: unset env -> error, no subprocess.run
# ---------------------------------------------------------------------------


def test_runner_raises_when_license_unset_and_does_not_invoke_docker(
    gateware, peripheral_dir, monkeypatch
):
    """Case 15: LM_LICENSE_FILE unset -> LicenseUnsetError, subprocess.run unused."""
    pd, _ = peripheral_dir
    called = []

    def fake_run(argv, *args, **kwargs):  # pragma: no cover - must NOT be called
        called.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    with pytest.raises(gateware.LicenseUnsetError):
        gateware.run_gateware_build(
            str(pd),
            "myplugin-gateware:latest-arm64",
            env={},
        )

    assert called == []


# ---------------------------------------------------------------------------
# AC-10 case 11: bitstream glob returns newest of many
# ---------------------------------------------------------------------------


def test_runner_returns_newest_bit_when_multiple_emitted(
    gateware, peripheral_dir, monkeypatch
):
    """Case 11: glob with two extracted .bit files of different mtimes -> newest wins."""
    pd, license_file = peripheral_dir
    bs = _bitstreams_dir(pd)
    older = os.path.join(bs, "sdk_old_extracted.bit")
    newer = os.path.join(bs, "sdk_new_extracted.bit")
    with open(older, "w") as fp:
        fp.write("old")
    time.sleep(0.05)
    with open(newer, "w") as fp:
        fp.write("new")
    # Belt-and-suspenders: force mtimes so the test isn't flaky on
    # coarse-granularity filesystems.
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    result = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert os.path.abspath(result) == os.path.abspath(newer)


# ---------------------------------------------------------------------------
# AC-10 case 12: no .bit -> clear FileNotFoundError naming the glob
# ---------------------------------------------------------------------------


def test_runner_raises_with_glob_in_message_when_no_bit_emitted(
    gateware, peripheral_dir, monkeypatch
):
    """Case 12: docker run succeeds but no .bit lands -> FileNotFoundError
    whose message names the expected glob pattern.
    """
    pd, license_file = peripheral_dir
    _bitstreams_dir(pd)  # exists but empty

    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    with pytest.raises(FileNotFoundError) as excinfo:
        gateware.run_gateware_build(
            str(pd),
            "myplugin-gateware:latest-arm64",
            env={"LM_LICENSE_FILE": str(license_file)},
        )

    assert "sdk_*_extracted.bit" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Extracted-bitstream selection: the raw sdk_*.bit is ignored
# ---------------------------------------------------------------------------


def test_runner_ignores_raw_bit_and_picks_extracted(
    gateware, peripheral_dir, monkeypatch
):
    """When both the raw sdk_*.bit and its sdk_*_extracted.bit sit side by
    side, the runner must select the extracted variant — even when the raw
    .bit is newer by mtime (the raw glob would otherwise win on mtime).
    """
    pd, license_file = peripheral_dir
    bs = _bitstreams_dir(pd)
    raw = os.path.join(bs, "sdk_topbuild.bit")
    extracted = os.path.join(bs, "sdk_topbuild_extracted.bit")
    with open(raw, "w") as fp:
        fp.write("raw")
    with open(extracted, "w") as fp:
        fp.write("extracted")
    # Make the raw .bit strictly newer so a mtime-only selection would pick it.
    os.utime(extracted, (1_000_000, 1_000_000))
    os.utime(raw, (2_000_000, 2_000_000))

    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gateware.subprocess, "run", fake_run)

    result = gateware.run_gateware_build(
        str(pd),
        "myplugin-gateware:latest-arm64",
        env={"LM_LICENSE_FILE": str(license_file)},
    )

    assert os.path.abspath(result) == os.path.abspath(extracted)
