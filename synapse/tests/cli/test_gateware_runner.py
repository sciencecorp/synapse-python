"""Public SDK runner contract: return the image this build produced.

Only files the build wrote or changed are candidates. A schema-2 summary names
the image outright; otherwise the newest native ``sdk_*.bit`` wins, falling
back to the newest ``sdk_*_extracted.bit``.
"""

from __future__ import annotations

import importlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

IMAGE_TAG = "myplugin-gateware:latest-arm64"


# Earlier builds' files sit an hour in the past; this build's land whole
# seconds after "now", so ordering never depends on the wall clock moving.
def _stale_ns() -> int:
    return time.time_ns() - 3600 * 10**9


def _new_ns(order: int) -> int:
    return time.time_ns() + order * 10**9


def _write(path: Path, data: bytes, mtime_ns: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _summary(bit_path: Path, mtime_ns: int, **fields) -> Path:
    """Write *bit_path*'s same-stem ``.summary.json``."""
    path = bit_path.with_name(bit_path.name.removesuffix(".bit") + ".summary.json")
    return _write(path, json.dumps(fields).encode(), mtime_ns)


def _project_args(argv) -> list[str]:
    """Every ``--project`` value in *argv*, including inside ``bash -lc``."""
    values = []
    for element in argv:
        tokens = shlex.split(str(element))
        values += [b for a, b in zip(tokens, tokens[1:]) if a == "--project"]
    return values


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
def bitstreams(peripheral_dir):
    path = peripheral_dir[0] / "src" / "gateware" / "build" / "bitstreams"
    path.mkdir(parents=True)
    return path


@pytest.fixture()
def build(gateware, peripheral_dir, bitstreams, monkeypatch):
    """Run the build once; *emit* plays the SDK, writing into ``bitstreams``."""
    pd, license_file = peripheral_dir

    def run(emit) -> Path:
        before = len(run.argvs)

        def fake_run(argv, *args, **kwargs):
            assert len(run.argvs) == before, "build invoked the SDK twice"
            run.argvs.append(argv)
            emit(bitstreams)
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        monkeypatch.setattr(gateware.subprocess, "run", fake_run)
        selected = gateware.run_gateware_build(
            str(pd), IMAGE_TAG, env={"LM_LICENSE_FILE": str(license_file)}
        )
        assert len(run.argvs) == before + 1
        assert Path(selected).is_absolute()
        return Path(selected)

    run.argvs = []
    return run


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
        gateware.run_gateware_build(str(pd), IMAGE_TAG, env={})

    assert called == []


def test_runner_passes_default_project_to_sdk(build):
    build(lambda bs: _write(bs / "sdk_gateware.bit", b"native", _new_ns(1)))

    assert [_project_args(argv) for argv in build.argvs] == [["src/gateware"]]


# ---------------------------------------------------------------------------
# Legacy rule (summary schema_version missing or 1)
# ---------------------------------------------------------------------------

legacy_schema = pytest.mark.parametrize(
    "schema_field",
    [{}, {"schema_version": 1}],
    ids=["schema_version_missing", "schema_version_1"],
)


def test_runner_returns_native_only_output(build, bitstreams):
    selected = build(
        lambda bs: _write(bs / "sdk_gateware.bit", b"\x96\x01\x80\x7f", _new_ns(1))
    )

    assert selected == bitstreams / "sdk_gateware.bit"
    assert selected.read_bytes() == b"\x96\x01\x80\x7f"


def test_runner_prefers_native_over_newer_extracted(build, bitstreams):
    def emit(bs):
        _write(bs / "sdk_gateware.bit", b"native", _new_ns(1))
        _write(bs / "sdk_gateware_extracted.bit", b"extracted", _new_ns(3))

    selected = build(emit)

    assert selected == bitstreams / "sdk_gateware.bit"
    assert selected.read_bytes() == b"native"


def test_runner_returns_newest_native_candidate(build, bitstreams):
    def emit(bs):
        _write(bs / "sdk_old.bit", b"old native", _new_ns(1))
        _write(bs / "sdk_new.bit", b"new native", _new_ns(2))
        _write(bs / "sdk_new_extracted.bit", b"extracted decoy", _new_ns(3))

    selected = build(emit)

    assert selected == bitstreams / "sdk_new.bit"
    assert selected.read_bytes() == b"new native"


def test_runner_falls_back_to_extracted_when_no_native_image(build, bitstreams):
    selected = build(
        lambda bs: _write(bs / "sdk_gateware_extracted.bit", b"extracted", _new_ns(1))
    )

    assert selected == bitstreams / "sdk_gateware_extracted.bit"
    assert selected.read_bytes() == b"extracted"


def test_runner_falls_back_to_newest_extracted_candidate(build, bitstreams):
    def emit(bs):
        _write(bs / "sdk_new_extracted.bit", b"new extracted", _new_ns(2))
        _write(bs / "sdk_old_extracted.bit", b"old extracted", _new_ns(1))

    selected = build(emit)

    assert selected == bitstreams / "sdk_new_extracted.bit"
    assert selected.read_bytes() == b"new extracted"


def test_runner_ignores_newer_non_sdk_and_non_bit_files(build, bitstreams):
    def emit(bs):
        _write(bs / "sdk_gateware.bit", b"native", _new_ns(1))
        _write(bs / "gateware.bit", b"decoy", _new_ns(3))
        _write(bs / "sdk_gateware.mcs", b"decoy", _new_ns(3))

    assert build(emit) == bitstreams / "sdk_gateware.bit"


@legacy_schema
def test_legacy_summary_ignores_bitstream_field_and_prefers_native(
    build, bitstreams, schema_field
):
    """Below schema 2 a ``bitstream`` key carries no meaning."""

    def emit(bs):
        _write(bs / "sdk_gateware.bit", b"native", _new_ns(1))
        _write(bs / "sdk_gateware_extracted.bit", b"extracted", _new_ns(2))
        _summary(
            bs / "sdk_gateware.bit",
            _new_ns(1),
            bitstream="sdk_gateware_extracted.bit",
            **schema_field,
        )

    assert build(emit) == bitstreams / "sdk_gateware.bit"


@legacy_schema
def test_legacy_summary_falls_back_to_extracted(build, bitstreams, schema_field):
    def emit(bs):
        _write(bs / "sdk_gateware_extracted.bit", b"extracted", _new_ns(1))
        _summary(bs / "sdk_gateware_extracted.bit", _new_ns(1), **schema_field)

    assert build(emit) == bitstreams / "sdk_gateware_extracted.bit"


# ---------------------------------------------------------------------------
# Only this build's output counts
# ---------------------------------------------------------------------------


def test_runner_returns_extracted_image_when_stale_native_predates_build(
    build, bitstreams
):
    """A native image left by an earlier build must not mask this build's
    extracted-only output."""
    _write(bitstreams / "sdk_x.bit", b"earlier native", _stale_ns())

    selected = build(
        lambda bs: _write(bs / "sdk_y_extracted.bit", b"this build", _new_ns(1))
    )

    assert selected == bitstreams / "sdk_y_extracted.bit"
    assert selected.read_bytes() == b"this build"


def test_runner_ignores_unchanged_preexisting_file_with_future_mtime(build, bitstreams):
    """Unchanged means unchanged, even when the old file's mtime is ahead."""
    _write(bitstreams / "sdk_x.bit", b"earlier native", _new_ns(100))

    selected = build(
        lambda bs: _write(bs / "sdk_y_extracted.bit", b"this build", _new_ns(1))
    )

    assert selected == bitstreams / "sdk_y_extracted.bit"


def test_runner_returns_preexisting_image_the_build_rewrote(build, bitstreams):
    _write(bitstreams / "sdk_gateware.bit", b"earlier bytes", _stale_ns())

    selected = build(
        lambda bs: _write(bs / "sdk_gateware.bit", b"rebuilt bytes!", _new_ns(1))
    )

    assert selected == bitstreams / "sdk_gateware.bit"
    assert selected.read_bytes() == b"rebuilt bytes!"


def test_sequential_builds_each_return_their_own_native_image(build, bitstreams):
    first = build(lambda bs: _write(bs / "sdk_a.bit", b"build A", _new_ns(5)))
    # B's image is older on disk than A's: newness to *this* build is what
    # matters, not mtime across builds.
    second = build(lambda bs: _write(bs / "sdk_b.bit", b"build B", _new_ns(2)))

    assert first == bitstreams / "sdk_a.bit"
    assert second == bitstreams / "sdk_b.bit"
    assert second.read_bytes() == b"build B"


def test_runner_raises_when_only_non_candidate_files_emitted(build):
    def emit(bs):
        _write(bs / "gateware.bit", b"decoy", _new_ns(1))
        _write(bs / "sdk_gateware.mcs", b"decoy", _new_ns(1))

    with pytest.raises(FileNotFoundError):
        build(emit)


def test_runner_raises_when_build_emits_nothing(build):
    with pytest.raises(FileNotFoundError):
        build(lambda bs: None)


def test_runner_raises_when_build_emits_nothing_but_old_images_exist(build, bitstreams):
    _write(bitstreams / "sdk_x.bit", b"earlier native", _stale_ns())
    _write(bitstreams / "sdk_x_extracted.bit", b"earlier extracted", _stale_ns())
    _summary(bitstreams / "sdk_x.bit", _stale_ns(), schema_version=1)

    with pytest.raises(FileNotFoundError):
        build(lambda bs: None)


# ---------------------------------------------------------------------------
# Schema 2: the summary names the image
# ---------------------------------------------------------------------------


def test_schema2_summary_selects_named_image_over_newer_native(build, bitstreams):
    def emit(bs):
        _write(bs / "sdk_gw_extracted.bit", b"named image", _new_ns(1))
        _summary(
            bs / "sdk_gw_extracted.bit",
            _new_ns(1),
            schema_version=2,
            bitstream="sdk_gw_extracted.bit",
        )
        _write(bs / "sdk_other.bit", b"newer native decoy", _new_ns(5))

    selected = build(emit)

    assert selected == bitstreams / "sdk_gw_extracted.bit"
    assert selected.read_bytes() == b"named image"


def _schema2_emitter(bitstream, extra=lambda bs: None, schema_version=2):
    """Emit ``sdk_gw.bit`` plus its summary, whose ``bitstream`` is *bitstream*."""

    def emit(bs):
        _write(bs / "sdk_gw.bit", b"native", _new_ns(1))
        extra(bs)
        _summary(
            bs / "sdk_gw.bit",
            _new_ns(1),
            schema_version=schema_version,
            bitstream=bitstream,
        )

    return emit


def test_schema2_summary_selects_its_own_sibling_image(build, bitstreams):
    def emit(bs):
        _write(bs / "sdk_other.bit", b"newer native decoy", _new_ns(5))

    selected = build(_schema2_emitter("sdk_gw.bit", extra=emit))

    assert selected == bitstreams / "sdk_gw.bit"
    assert selected.read_bytes() == b"native"


def test_schema2_rejects_summary_naming_a_different_new_image(build):
    """Each summary may only name its own ``<stem>.bit``, even when the other
    image is a valid file this build wrote."""
    emit = _schema2_emitter(
        "sdk_other.bit",
        extra=lambda bs: _write(bs / "sdk_other.bit", b"other", _new_ns(2)),
    )

    with pytest.raises(ValueError):
        build(emit)


@pytest.mark.parametrize(
    "bitstream",
    # The backslash form is a legal POSIX file name, so only the rule rejects it.
    ["sub/sdk_gw.bit", "sub\\sdk_gw.bit", "../sdk_gw.bit"],
    ids=["forward_slash", "backslash", "parent_relative"],
)
def test_schema2_rejects_bitstream_that_is_not_a_basename(build, bitstream):
    """Rejected even though a fresh image exists where the path points."""
    emit = _schema2_emitter(
        bitstream, extra=lambda bs: _write(bs / bitstream, b"escape", _new_ns(2))
    )

    with pytest.raises(ValueError):
        build(emit)


def test_schema2_rejects_absolute_bitstream(build, bitstreams):
    with pytest.raises(ValueError):
        build(_schema2_emitter(str(bitstreams / "sdk_gw.bit")))


def test_schema2_rejects_bitstream_without_bit_suffix(build):
    emit = _schema2_emitter(
        "sdk_gw.mcs", extra=lambda bs: _write(bs / "sdk_gw.mcs", b"mcs", _new_ns(1))
    )

    with pytest.raises(ValueError):
        build(emit)


def test_schema2_rejects_missing_sibling_image(build):
    """A fresh fallback image must not paper over the summary's missing one."""

    def emit(bs):
        _write(bs / "sdk_other.bit", b"fallback native", _new_ns(1))
        _summary(
            bs / "sdk_gw.bit", _new_ns(1), schema_version=2, bitstream="sdk_gw.bit"
        )

    with pytest.raises(FileNotFoundError):
        build(emit)


def test_schema2_rejects_sibling_image_from_an_earlier_build(build, bitstreams):
    _write(bitstreams / "sdk_old.bit", b"earlier native", _stale_ns())

    def emit(bs):
        _write(bs / "sdk_other.bit", b"fallback native", _new_ns(1))
        _summary(
            bs / "sdk_old.bit", _new_ns(1), schema_version=2, bitstream="sdk_old.bit"
        )

    with pytest.raises((ValueError, FileNotFoundError)):
        build(emit)


@pytest.mark.parametrize("schema_version", [3, 17])
def test_newer_summary_schema_asks_for_upgrade(build, schema_version):
    with pytest.raises(ValueError) as exc:
        build(_schema2_emitter("sdk_gw.bit", schema_version=schema_version))

    message = str(exc.value)
    assert str(schema_version) in message
    assert "upgrade" in message.lower()


# ---------------------------------------------------------------------------
# Summaries left by earlier builds carry no weight
# ---------------------------------------------------------------------------


def test_stale_newer_schema_summary_is_ignored_next_to_fresh_image(build, bitstreams):
    """A schema-3 summary from an earlier build must not block this build."""
    _summary(
        bitstreams / "sdk_gw.bit",
        _stale_ns(),
        schema_version=3,
        bitstream="sdk_gw.bit",
    )

    selected = build(lambda bs: _write(bs / "sdk_gw.bit", b"fresh", _new_ns(1)))

    assert selected == bitstreams / "sdk_gw.bit"
    assert selected.read_bytes() == b"fresh"


def test_stale_schema2_summary_does_not_redirect_selection(build, bitstreams):
    _write(bitstreams / "sdk_old.bit", b"earlier native", _stale_ns())
    _summary(
        bitstreams / "sdk_old.bit",
        _stale_ns(),
        schema_version=2,
        bitstream="sdk_old.bit",
    )

    selected = build(
        lambda bs: _write(bs / "sdk_new_extracted.bit", b"fresh", _new_ns(1))
    )

    assert selected == bitstreams / "sdk_new_extracted.bit"


# ---------------------------------------------------------------------------
# Schema 2 without a usable ``bitstream`` field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bitstream_field",
    [{}, {"bitstream": None}, {"bitstream": 7}, {"bitstream": ["sdk_gw.bit"]}],
    ids=["missing", "null", "integer", "list"],
)
def test_schema2_summary_without_string_bitstream_raises(build, bitstream_field):
    def emit(bs):
        _write(bs / "sdk_gw.bit", b"native", _new_ns(1))
        _summary(bs / "sdk_gw.bit", _new_ns(1), schema_version=2, **bitstream_field)

    with pytest.raises(ValueError):
        build(emit)
