"""Custom gateware packaging: summary parsing, deb selection, gateware deb.

Covers the synapse-python half of the custom-bitstreams design (spec:
docs/superpowers/specs/2026-06-09-custom-gateware-bitstreams-design.md):

  * ``gateware.summary_path_for`` / ``gateware.read_usb_pid``
  * ``build.find_deb_package`` package_name filtering
  * ``peripherals.build_gateware_deb`` staging layout + fpm invocation

The two-deb build/deploy command flows live in test_half_selectors.py.
"""

from __future__ import annotations

import importlib
import json
import os

import pytest


@pytest.fixture()
def gateware():
    """Lazy import (mirrors test_half_selectors.py) so conftest stubs apply."""
    return importlib.import_module("synapse.cli.gateware")


@pytest.fixture()
def buildmod():
    return importlib.import_module("synapse.cli.build")


@pytest.fixture()
def peripherals():
    return importlib.import_module("synapse.cli.peripherals")


def _write_summary(bit_path, payload):
    """Drop ``<stem>.summary.json`` next to *bit_path*; payload str = raw."""
    stem, _ = os.path.splitext(str(bit_path))
    path = f"{stem}.summary.json"
    with open(path, "w", encoding="utf-8") as fp:
        if isinstance(payload, str):
            fp.write(payload)
        else:
            json.dump(payload, fp)
    return path


# ---------------------------------------------------------------------------
# gateware.summary_path_for / gateware.read_usb_pid
# ---------------------------------------------------------------------------


def test_summary_path_for_same_stem(gateware, tmp_path):
    bit = tmp_path / "sdk_via_v0.0.0.bit"
    assert gateware.summary_path_for(str(bit)) == str(
        tmp_path / "sdk_via_v0.0.0.summary.json"
    )


def test_read_usb_pid_happy_path(gateware, tmp_path):
    """SDK 1.0.2 shape: top-level hex string, project without usb_pid."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(
        bit,
        {
            "schema_version": 1,
            "sdk_version": "1.0.2",
            "usb_pid": "0x000B",
            "project": {"name": "gateware", "git_sha": "e6890a3"},
        },
    )
    assert gateware.read_usb_pid(str(bit)) == 11


def test_read_usb_pid_happy_path_0x0004(gateware, tmp_path):
    """Top-level hex string "0x0004" -> 4."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x0004", "project": {"name": "gateware"}})
    assert gateware.read_usb_pid(str(bit)) == 4


def test_read_usb_pid_missing_summary_raises(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    with pytest.raises(FileNotFoundError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "summary" in str(exc_info.value).lower()


def test_read_usb_pid_invalid_json_raises(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, "{not json")
    with pytest.raises(ValueError):
        gateware.read_usb_pid(str(bit))


def test_read_usb_pid_missing_key_raises(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    # Real shape observed from the SDK today (usb_pid not yet emitted).
    _write_summary(bit, {"project": {"name": "gateware", "git_sha": "77d672b"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_rejects_bool(gateware, tmp_path):
    """Booleans at top level must be rejected (bool is not a hex string)."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": True, "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_non_object_summary_raises(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, [1, 2])
    with pytest.raises(ValueError):
        gateware.read_usb_pid(str(bit))


# ---------------------------------------------------------------------------
# Strict contract: top-level hex string only (SDK 1.0.2 shape)
# ---------------------------------------------------------------------------


def test_read_usb_pid_old_project_shape_raises(gateware, tmp_path):
    """The OLD shape {"project": {"usb_pid": 4}} (no top-level) -> ValueError.

    Contract decision: project.usb_pid is no longer consulted; the top-level
    hex-string is the only accepted form.
    """
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"project": {"usb_pid": 4}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_toplevel_int_raises(gateware, tmp_path):
    """Top-level usb_pid as a plain integer -> ValueError (must be hex string)."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": 11, "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_toplevel_bool_raises(gateware, tmp_path):
    """Top-level bool -> ValueError (bool is not a hex string)."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": True, "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_rejects_unparseable_string(gateware, tmp_path):
    """Non-hex string at top level -> ValueError mentioning usb_pid."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "xyz", "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_rejects_empty_string(gateware, tmp_path):
    """Empty string at top level -> ValueError mentioning usb_pid."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "", "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_rejects_zero_hex_string(gateware, tmp_path):
    """\"0x0000\" is out of range (must be 1..0xFFFF)."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x0000", "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_rejects_overflow_hex_string(gateware, tmp_path):
    """\"0x10000\" is above uint16 range."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x10000", "project": {"name": "gateware"}})
    with pytest.raises(ValueError) as exc_info:
        gateware.read_usb_pid(str(bit))
    assert "usb_pid" in str(exc_info.value)


def test_read_usb_pid_accepts_max_ffff(gateware, tmp_path):
    """\"0xFFFF\" is the maximum valid value -> 65535."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0xFFFF", "project": {"name": "gateware"}})
    assert gateware.read_usb_pid(str(bit)) == 65535


# ---------------------------------------------------------------------------
# gateware.read_project_name
# ---------------------------------------------------------------------------


def test_read_project_name_happy_path(gateware, tmp_path):
    """SDK 1.0.2 shape: project.name is a non-empty string."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(
        bit,
        {
            "usb_pid": "0x000B",
            "project": {"name": "gateware", "git_sha": "e6890a3"},
        },
    )
    assert gateware.read_project_name(str(bit)) == "gateware"


def test_read_project_name_missing_summary_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    assert gateware.read_project_name(str(bit)) is None


def test_read_project_name_missing_project_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x000B"})
    assert gateware.read_project_name(str(bit)) is None


def test_read_project_name_missing_name_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x000B", "project": {"git_sha": "abc123"}})
    assert gateware.read_project_name(str(bit)) is None


def test_read_project_name_empty_string_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x000B", "project": {"name": ""}})
    assert gateware.read_project_name(str(bit)) is None


def test_read_project_name_invalid_json_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, "{not json")
    assert gateware.read_project_name(str(bit)) is None


# ---------------------------------------------------------------------------
# build.find_deb_package package_name filtering
# ---------------------------------------------------------------------------


def test_find_deb_package_unfiltered_back_compat(buildmod, tmp_path):
    (tmp_path / "anything_0.1.0_arm64.deb").write_text("deb")
    found = buildmod.find_deb_package(str(tmp_path))
    assert found is not None and found.endswith("anything_0.1.0_arm64.deb")


def test_find_deb_package_filters_by_package_name(buildmod, tmp_path):
    # A peripheral dist/ now holds BOTH debs; the driver name is a strict
    # prefix of the gateware name, so matching must be on "<name>_".
    (tmp_path / "via_0.1.0_arm64.deb").write_text("deb")
    (tmp_path / "via-gateware_0.1.0_arm64.deb").write_text("deb")
    driver = buildmod.find_deb_package(str(tmp_path), "via")
    gw = buildmod.find_deb_package(str(tmp_path), "via-gateware")
    assert driver is not None and driver.endswith(os.sep + "via_0.1.0_arm64.deb")
    assert gw is not None and gw.endswith(os.sep + "via-gateware_0.1.0_arm64.deb")


def test_find_deb_package_no_match_returns_none(buildmod, tmp_path, capsys):
    (tmp_path / "other_0.1.0_arm64.deb").write_text("deb")
    assert buildmod.find_deb_package(str(tmp_path), "via") is None
    assert "could not find" in capsys.readouterr().out.lower()


def test_find_deb_package_version_anchored_prefix_skips_stale(buildmod, tmp_path):
    # dist/ accumulates old versions; callers anchor the prefix with the
    # version so a stale 0.1.0 deb never shadows the fresh 0.2.0 build.
    (tmp_path / "via_0.1.0_arm64.deb").write_text("deb")
    (tmp_path / "via_0.2.0_arm64.deb").write_text("deb")
    found = buildmod.find_deb_package(str(tmp_path), "via_0.2.0")
    assert found is not None and found.endswith(os.sep + "via_0.2.0_arm64.deb")


# ---------------------------------------------------------------------------
# peripherals.build_gateware_deb
# ---------------------------------------------------------------------------

# synapse/tests/cli/ is a package (has __init__.py), so import the helper
# package-qualified rather than relying on pytest's rootdir sys.path insert.
from synapse.tests.cli.conftest import fake_fpm_run


def _spy_mkdtemp(peripherals, monkeypatch, holder: list):
    real_mkdtemp = peripherals.tempfile.mkdtemp

    def spy(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        holder.append(d)
        return d

    monkeypatch.setattr(peripherals.tempfile, "mkdtemp", spy)


def test_build_gateware_deb_stages_bit_fragment_and_depends(
    peripherals, tmp_path, monkeypatch
):
    pd = tmp_path / "plugin"
    pd.mkdir()
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("BITSTREAM")
    manifest = {"name": "scifi-my-chip", "version": "0.2.0"}

    staging: list = []
    _spy_mkdtemp(peripherals, monkeypatch, staging)
    calls: list = []
    dist_dir = os.path.join(str(pd), "dist")
    monkeypatch.setattr(peripherals.subprocess, "run", fake_fpm_run(dist_dir, calls))

    ok = peripherals.build_gateware_deb(
        str(pd), manifest, bit_path=str(bit), usb_pid=4, display_name="my-gateware",
        version="0.2.0"
    )
    assert ok is True
    assert len(staging) == 1

    bit_dst = os.path.join(
        staging[0], "opt", "scifi", "bitstreams", "custom", "scifi-my-chip.bit"
    )
    frag_dst = os.path.join(
        staging[0], "opt", "scifi", "bitstreams", "custom",
        "scifi-my-chip.manifest.json",
    )
    assert os.path.exists(bit_dst), "bitstream staged under custom/ as <name>.bit"
    with open(frag_dst, "r", encoding="utf-8") as fh:
        frag = json.load(fh)
    assert frag == {
        "name": "scifi-my-chip",
        "display_name": "my-gateware",
        "usb_pid": 4,
        "artifact": "custom/scifi-my-chip.bit",
    }

    fpm_call = next(c for c in calls if "fpm" in c)
    assert fpm_call[fpm_call.index("-n") + 1] == "scifi-my-chip-gateware"
    assert fpm_call[fpm_call.index("--depends") + 1] == "axonprobe-bitstreams"
    # fpm input must be "opt" (not "."): postinstall.sh must NOT ship in the
    # payload, or the driver and gateware debs would dpkg-conflict on
    # /postinstall.sh.
    assert fpm_call[-1] == "opt"


def test_build_gateware_deb_omit_display_name_falls_back_to_plugin_name(
    peripherals, tmp_path, monkeypatch
):
    """Omitting display_name causes the fragment to use the plugin name as display_name."""
    pd = tmp_path / "plugin"
    pd.mkdir()
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("BITSTREAM")
    manifest = {"name": "scifi-my-chip", "version": "0.2.0"}

    staging: list = []
    _spy_mkdtemp(peripherals, monkeypatch, staging)
    calls: list = []
    dist_dir = os.path.join(str(pd), "dist")
    monkeypatch.setattr(peripherals.subprocess, "run", fake_fpm_run(dist_dir, calls))

    ok = peripherals.build_gateware_deb(
        str(pd), manifest, bit_path=str(bit), usb_pid=4, version="0.2.0"
    )
    assert ok is True
    frag_dst = os.path.join(
        staging[0], "opt", "scifi", "bitstreams", "custom",
        "scifi-my-chip.manifest.json",
    )
    with open(frag_dst, "r", encoding="utf-8") as fh:
        frag = json.load(fh)
    assert frag["display_name"] == "scifi-my-chip"


def test_build_gateware_deb_missing_bit_errors(peripherals, tmp_path, capsys):
    pd = tmp_path / "plugin"
    pd.mkdir()
    ok = peripherals.build_gateware_deb(
        str(pd), {"name": "x"}, bit_path=str(tmp_path / "nope.bit"), usb_pid=1
    )
    assert ok is False
    assert "not found" in capsys.readouterr().out.lower()
