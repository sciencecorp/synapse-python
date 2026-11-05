"""Custom gateware packaging: summary parsing, deb selection, gateware deb.

Covers the synapse-python half of the custom-bitstreams design (spec:
docs/superpowers/specs/2026-06-09-custom-gateware-bitstreams-design.md):

  * ``gateware.summary_path_for`` / ``gateware.read_usb_pid``
  * ``build.find_deb_package`` package_name filtering
  * ``peripherals.build_gateware_deb`` staging layout + fpm invocation: the
    image keeps its build file name under
    ``custom/artifacts/<identifier>/`` and the fragment points at it

The two-deb build/deploy command flows live in test_half_selectors.py.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest

from synapse.tests.cli.conftest import fake_fpm_run
from synapse.tests.cli.test_gateware_runner import _new_ns, _summary, _write


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
# gateware.read_identifier
# ---------------------------------------------------------------------------


def test_read_identifier_happy_path(gateware, tmp_path):
    """SDK 1.0.2 shape: target_profile + project.name -> '<profile>_<name>'."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(
        bit,
        {
            "usb_pid": "0x000B",
            "target_profile": "via-devkit",
            "project": {"name": "gateware", "git_sha": "e6890a3"},
        },
    )
    assert gateware.read_identifier(str(bit)) == "via-devkit_gateware"


def test_read_identifier_missing_target_profile_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x000B", "project": {"name": "gateware"}})
    assert gateware.read_identifier(str(bit)) is None


def test_read_identifier_missing_project_name_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(
        bit, {"usb_pid": "0x000B", "target_profile": "via-devkit", "project": {}}
    )
    assert gateware.read_identifier(str(bit)) is None


def test_read_identifier_missing_summary_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    assert gateware.read_identifier(str(bit)) is None


def test_read_identifier_invalid_json_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, "{not json")
    assert gateware.read_identifier(str(bit)) is None


# ---------------------------------------------------------------------------
# gateware.read_git_sha
# ---------------------------------------------------------------------------


def test_read_git_sha_happy_path(gateware, tmp_path):
    """SDK 1.0.2 shape: project.git_sha is a non-empty string."""
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(
        bit,
        {
            "usb_pid": "0x000B",
            "target_profile": "via-devkit",
            "project": {"name": "gateware", "git_sha": "e6890a3"},
        },
    )
    assert gateware.read_git_sha(str(bit)) == "e6890a3"


def test_read_git_sha_missing_git_sha_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"usb_pid": "0x000B", "project": {"name": "gateware"}})
    assert gateware.read_git_sha(str(bit)) is None


def test_read_git_sha_empty_string_returns_none(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(
        bit, {"usb_pid": "0x000B", "project": {"name": "gateware", "git_sha": ""}}
    )
    assert gateware.read_git_sha(str(bit)) is None


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


def _spy_mkdtemp(peripherals, monkeypatch, holder: list):
    real_mkdtemp = peripherals.tempfile.mkdtemp

    def spy(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        holder.append(d)
        return d

    monkeypatch.setattr(peripherals.tempfile, "mkdtemp", spy)


BITSTREAMS = Path("opt", "scifi", "bitstreams")
VERSIONED_BIT = "sdk_nerv512u-devkit_gateware_v0.3.7_ab12cd34_11052026_1530.bit"


def _build(peripherals, monkeypatch, tmp_path, bit_name, *, payload, **kwargs):
    """Run build_gateware_deb on a fresh plugin dir with fpm stubbed out.

    Returns (ok, staging root, recorded subprocess argv list).
    """
    pd = tmp_path / f"plugin-{len(list(tmp_path.iterdir()))}"
    pd.mkdir()
    bit = pd / "build" / bit_name
    bit.parent.mkdir()
    bit.write_bytes(payload)

    staging: list = []
    _spy_mkdtemp(peripherals, monkeypatch, staging)
    calls: list = []
    monkeypatch.setattr(
        peripherals.subprocess, "run", fake_fpm_run(str(pd / "dist"), calls)
    )
    ok = peripherals.build_gateware_deb(
        str(pd),
        {"name": "scifi-my-chip", "version": "0.2.0"},
        bit_path=str(bit),
        usb_pid=4,
        version="0.2.0",
        **kwargs,
    )
    assert len(staging) == 1
    return ok, Path(staging[0]), calls


def _staged_bits(root: Path) -> list:
    return sorted((root / BITSTREAMS / "custom").rglob("*.bit"))


def _fragment(root: Path, identifier: str) -> dict:
    path = root / BITSTREAMS / "custom" / f"{identifier}.manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _fpm_name(calls: list) -> str:
    fpm_call = next(c for c in calls if "fpm" in c)
    return fpm_call[fpm_call.index("-n") + 1]


def test_build_gateware_deb_stages_bit_fragment_and_depends(
    peripherals, tmp_path, monkeypatch
):
    """With bitstream_name and git_hash: image under artifacts/<identifier>/."""
    payload = b"\x96\x01BITSTREAM\x00"
    ok, root, calls = _build(
        peripherals,
        monkeypatch,
        tmp_path,
        "sdk_x.bit",
        payload=payload,
        bitstream_name="via-devkit_gateware",
        git_hash="e6890a3",
    )
    assert ok is True

    image = root / BITSTREAMS / "custom/artifacts/via-devkit_gateware/sdk_x.bit"
    assert _staged_bits(root) == [image]
    assert image.read_bytes() == payload
    assert _fragment(root, "via-devkit_gateware") == {
        "name": "via-devkit_gateware",
        "usb_pid": 4,
        "artifact": "custom/artifacts/via-devkit_gateware/sdk_x.bit",
        "git_hash": "e6890a3",
    }

    fpm_call = next(c for c in calls if "fpm" in c)
    assert _fpm_name(calls) == "axon-gateware-via-devkit-gateware"
    assert fpm_call[fpm_call.index("--depends") + 1] == "axonprobe-bitstreams"
    # fpm input must be "opt" (not "."): postinstall.sh must NOT ship in the
    # payload, or the driver and gateware debs would dpkg-conflict on
    # /postinstall.sh.
    assert fpm_call[-1] == "opt"


def test_build_gateware_deb_omit_bitstream_name_falls_back_to_plugin_name(
    peripherals, tmp_path, monkeypatch
):
    """Omitting bitstream_name: keyed on plugin name, no git_hash key."""
    ok, root, calls = _build(
        peripherals, monkeypatch, tmp_path, "sdk_x.bit", payload=b"BITSTREAM"
    )
    assert ok is True

    image = root / BITSTREAMS / "custom/artifacts/scifi-my-chip/sdk_x.bit"
    assert _staged_bits(root) == [image]
    assert _fragment(root, "scifi-my-chip") == {
        "name": "scifi-my-chip",
        "usb_pid": 4,
        "artifact": "custom/artifacts/scifi-my-chip/sdk_x.bit",
    }
    assert _fpm_name(calls) == "axon-gateware-scifi-my-chip"


@pytest.mark.parametrize(
    "bit_name",
    [VERSIONED_BIT, "sdk_nerv512u-devkit_gateware_extracted.bit"],
    ids=["versioned", "extracted"],
)
def test_build_gateware_deb_keeps_build_file_name(
    peripherals, tmp_path, monkeypatch, bit_name
):
    """The build's own file name is kept verbatim, never renamed to <id>.bit."""
    payload = bytes(range(256))
    ok, root, calls = _build(
        peripherals,
        monkeypatch,
        tmp_path,
        bit_name,
        payload=payload,
        bitstream_name="nerv512u-devkit_gateware",
        git_hash="ab12cd34",
    )
    assert ok is True

    custom = root / BITSTREAMS / "custom"
    image = custom / "artifacts" / "nerv512u-devkit_gateware" / bit_name
    assert _staged_bits(root) == [image]
    assert image.read_bytes() == payload
    assert not (custom / "nerv512u-devkit_gateware.bit").exists()
    assert _fragment(root, "nerv512u-devkit_gateware") == {
        "name": "nerv512u-devkit_gateware",
        "usb_pid": 4,
        "artifact": f"custom/artifacts/nerv512u-devkit_gateware/{bit_name}",
        "git_hash": "ab12cd34",
    }
    assert _fpm_name(calls) == "axon-gateware-nerv512u-devkit-gateware"


@pytest.mark.parametrize("bitstream_name", ["via-devkit_gateware", None])
def test_build_gateware_deb_fragment_artifact_resolves_to_staged_image(
    peripherals, tmp_path, monkeypatch, bitstream_name
):
    """Fragment ``artifact`` (relative to opt/scifi/bitstreams) is the image."""
    payload = b"\x69\x80IMAGE"
    ok, root, _ = _build(
        peripherals,
        monkeypatch,
        tmp_path,
        VERSIONED_BIT,
        payload=payload,
        bitstream_name=bitstream_name,
    )
    assert ok is True

    identifier = bitstream_name or "scifi-my-chip"
    resolved = root / BITSTREAMS / _fragment(root, identifier)["artifact"]
    assert _staged_bits(root) == [resolved]
    assert resolved.read_bytes() == payload


def test_build_gateware_deb_distinct_identifiers_never_share_a_path(
    peripherals, tmp_path, monkeypatch
):
    """Same build file name, two identifiers: no on-device path collides."""
    payloads = {"alpha_gateware": b"ALPHA", "beta_gateware": b"BETA"}
    staged = {}
    for identifier, payload in payloads.items():
        ok, root, _ = _build(
            peripherals,
            monkeypatch,
            tmp_path,
            VERSIONED_BIT,
            payload=payload,
            bitstream_name=identifier,
        )
        assert ok is True
        staged[identifier] = {
            p.relative_to(root) for p in (root / "opt").rglob("*") if p.is_file()
        }

    assert staged["alpha_gateware"].isdisjoint(staged["beta_gateware"])


def test_build_gateware_deb_missing_bit_errors(peripherals, tmp_path, capsys):
    pd = tmp_path / "plugin"
    pd.mkdir()
    ok = peripherals.build_gateware_deb(
        str(pd), {"name": "x"}, bit_path=str(tmp_path / "nope.bit"), usb_pid=1
    )
    assert ok is False
    assert "not found" in capsys.readouterr().out.lower()


def test_selected_native_bytes_and_summary_become_custom_package(
    gateware, peripherals, tmp_path, monkeypatch
):
    pd = tmp_path / "plugin"
    bitstreams = pd / "src" / "gateware" / "build" / "bitstreams"
    native = bitstreams / "sdk_profile-alpha_gateware.bit"
    native_payload = b"\x96\x01\x80\x7f\x00\xa5"

    def emit_sdk_outputs():
        _write(native, native_payload, _new_ns(1))
        _summary(
            native,
            _new_ns(1),
            schema_version=1,
            usb_pid="0x000B",
            target_profile="profile-alpha",
            project={"name": "gateware", "git_sha": "123abcd"},
        )
        extracted = bitstreams / "sdk_profile-alpha_gateware_extracted.bit"
        _write(extracted, b"\x69\x80\x01\xfe\x00\xa5", _new_ns(2))
        _summary(
            extracted,
            _new_ns(2),
            schema_version=1,
            usb_pid="0x0004",
            target_profile="wrong-profile",
            project={"name": "decoy", "git_sha": "badbeef"},
        )

    staging = []
    _spy_mkdtemp(peripherals, monkeypatch, staging)
    fpm_run = fake_fpm_run(str(pd / "dist"), [])

    def fake_run(argv, *args, **kwargs):
        # The SDK build writes its images; every other call goes to the fpm stub.
        if any("axon-peripheral-sdk build" in str(element) for element in argv):
            emit_sdk_outputs()
        return fpm_run(argv, *args, **kwargs)

    monkeypatch.setattr(peripherals.subprocess, "run", fake_run)

    selected = gateware.run_gateware_build(
        str(pd), "fake-gw:latest", env={"LM_LICENSE_FILE": "7788@licenseserver"}
    )
    ok = peripherals.build_gateware_deb(
        str(pd),
        {"name": "scifi-plugin", "version": "0.2.0"},
        bit_path=selected,
        usb_pid=gateware.read_usb_pid(selected),
        bitstream_name=gateware.read_identifier(selected),
        git_hash=gateware.read_git_sha(selected),
        version="0.2.0",
    )

    assert ok is True
    root = Path(staging[0])
    bit_name = Path(selected).name
    image = root / BITSTREAMS / "custom/artifacts/profile-alpha_gateware" / bit_name
    assert image.read_bytes() == native_payload
    assert _staged_bits(root) == [image]
    assert _fragment(root, "profile-alpha_gateware") == {
        "name": "profile-alpha_gateware",
        "usb_pid": 11,
        "artifact": f"custom/artifacts/profile-alpha_gateware/{bit_name}",
        "git_hash": "123abcd",
    }
