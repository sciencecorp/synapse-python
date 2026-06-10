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
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"project": {"name": "gateware", "usb_pid": 4}})
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


def test_read_usb_pid_rejects_non_int(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, {"project": {"usb_pid": "4"}})
    with pytest.raises(ValueError):
        gateware.read_usb_pid(str(bit))


def test_read_usb_pid_non_object_summary_raises(gateware, tmp_path):
    bit = tmp_path / "sdk_x.bit"
    bit.write_text("bit")
    _write_summary(bit, [1, 2])
    with pytest.raises(ValueError):
        gateware.read_usb_pid(str(bit))


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
