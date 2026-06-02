"""AC-10 / AC-5: unit tests for the LM_LICENSE_FILE helper.

The implementation lives in `synapse.cli.gateware` (per the plan's File
Structure section) and exposes:

    build_license_docker_args(env: Mapping[str, str]) -> list[str]
    LicenseUnsetError (subclass of RuntimeError)

Per AC-5:
  * **Unset / empty** -> raises ``LicenseUnsetError`` whose ``str()`` mentions
    ``LM_LICENSE_FILE``.
  * **port@host floating** (regex ``^[^/\\s]+@[^/\\s]+$``) -> returns
    ``["-e", f"LM_LICENSE_FILE={value}"]`` — no bind-mount.
  * **File path** (anything else) -> ``Path.expanduser().resolve(strict=True)``
    then returns ``["-v", f"{resolved}:/opt/lattice/license.dat:ro",
    "-e", "LM_LICENSE_FILE=/opt/lattice/license.dat"]``.

These tests are written before the implementation exists, so they MUST fail at
import time today (TDD).
"""

from __future__ import annotations


import importlib

import pytest


@pytest.fixture()
def gateware():
    """Lazy-import `synapse.cli.gateware`.

    Defers the import to test-run time so collection succeeds even before
    AC-5 lands. Each test individually fails with a clear ImportError if
    the module is missing — instead of one opaque collection-time error
    that masks every test.
    """
    return importlib.import_module("synapse.cli.gateware")


# ---------------------------------------------------------------------------
# Path mode
# ---------------------------------------------------------------------------


def test_path_mode_absolute_existing_file(gateware, tmp_path, monkeypatch):
    """Case 1: LM_LICENSE_FILE = absolute path to existing file -> bind-mount + MAC."""
    monkeypatch.setattr(gateware, "_host_mac_address", lambda: "aa:bb:cc:dd:ee:ff")
    license_file = tmp_path / "license.dat"
    license_file.write_text("FEATURE radiant ...")

    args = gateware.build_license_docker_args({"LM_LICENSE_FILE": str(license_file)})

    resolved = str(license_file.resolve())
    assert args == [
        "-v",
        f"{resolved}:/opt/lattice/license.dat:ro",
        "-e",
        "LM_LICENSE_FILE=/opt/lattice/license.dat",
        "--mac-address",
        "aa:bb:cc:dd:ee:ff",
    ]


def test_path_mode_nonexistent_file_raises(gateware, tmp_path):
    """Case 2: absolute path to non-existent file -> FileNotFoundError (strict resolve)."""
    missing = tmp_path / "nope.dat"
    with pytest.raises(FileNotFoundError):
        gateware.build_license_docker_args({"LM_LICENSE_FILE": str(missing)})


def test_path_with_at_in_directory_segment(gateware, tmp_path, monkeypatch):
    """Case 7: path containing '@' (e.g. /home/user@work/license.dat) — the
    regex rejects strings with '/', so this falls through to path mode.
    """
    monkeypatch.setattr(gateware, "_host_mac_address", lambda: "aa:bb:cc:dd:ee:ff")
    dir_with_at = tmp_path / "user@work"
    dir_with_at.mkdir()
    license_file = dir_with_at / "license.dat"
    license_file.write_text("FEATURE radiant ...")

    args = gateware.build_license_docker_args({"LM_LICENSE_FILE": str(license_file)})

    resolved = str(license_file.resolve())
    assert args == [
        "-v",
        f"{resolved}:/opt/lattice/license.dat:ro",
        "-e",
        "LM_LICENSE_FILE=/opt/lattice/license.dat",
        "--mac-address",
        "aa:bb:cc:dd:ee:ff",
    ]


def test_path_mode_expands_tilde(gateware, tmp_path, monkeypatch):
    """Case 10: ~ expansion via Path.expanduser()."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(gateware, "_host_mac_address", lambda: "aa:bb:cc:dd:ee:ff")
    license_file = tmp_path / "license.dat"
    license_file.write_text("FEATURE radiant ...")

    args = gateware.build_license_docker_args({"LM_LICENSE_FILE": "~/license.dat"})

    resolved = str(license_file.resolve())
    assert args == [
        "-v",
        f"{resolved}:/opt/lattice/license.dat:ro",
        "-e",
        "LM_LICENSE_FILE=/opt/lattice/license.dat",
        "--mac-address",
        "aa:bb:cc:dd:ee:ff",
    ]


def test_path_mode_skips_mac_when_unavailable(gateware, tmp_path, monkeypatch):
    """When uuid.getnode() falls back to a random MAC, _host_mac_address
    returns None and the helper must NOT inject --mac-address — passing a
    bogus random MAC into docker run is worse than passing nothing.
    """
    monkeypatch.setattr(gateware, "_host_mac_address", lambda: None)
    license_file = tmp_path / "license.dat"
    license_file.write_text("FEATURE radiant ...")

    args = gateware.build_license_docker_args({"LM_LICENSE_FILE": str(license_file)})

    assert "--mac-address" not in args
    resolved = str(license_file.resolve())
    assert args == [
        "-v",
        f"{resolved}:/opt/lattice/license.dat:ro",
        "-e",
        "LM_LICENSE_FILE=/opt/lattice/license.dat",
    ]


def test_floating_mode_skips_mac_address(gateware, monkeypatch):
    """Floating licenses talk to a license server over the network — hostid is
    irrelevant. Even when _host_mac_address returns a real MAC, the helper
    must not inject --mac-address in floating mode.
    """
    monkeypatch.setattr(gateware, "_host_mac_address", lambda: "aa:bb:cc:dd:ee:ff")
    args = gateware.build_license_docker_args(
        {"LM_LICENSE_FILE": "27000@licenseserver"}
    )
    assert "--mac-address" not in args
    assert args == ["-e", "LM_LICENSE_FILE=27000@licenseserver"]


# ---------------------------------------------------------------------------
# port@host (floating) mode
# ---------------------------------------------------------------------------


def test_floating_single_server_named_host(gateware):
    """Case 3: single-server port@host with named domain — accepted as floating."""
    args = gateware.build_license_docker_args(
        {"LM_LICENSE_FILE": "1710@lic.example.org"}
    )
    assert args == ["-e", "LM_LICENSE_FILE=1710@lic.example.org"]
    # Critically, no -v flag — port@host mode is bind-mount-free.
    assert "-v" not in args


def test_floating_port_number_bare_host(gateware):
    """Case 4: single-server `27000@licenseserver` (bare hostname)."""
    args = gateware.build_license_docker_args(
        {"LM_LICENSE_FILE": "27000@licenseserver"}
    )
    assert args == ["-e", "LM_LICENSE_FILE=27000@licenseserver"]
    assert "-v" not in args


def test_floating_multi_server_redundant(gateware):
    """Case 5: multi-server FlexLM redundancy `port1@host1:port2@host2`."""
    value = "27000@host1:27000@host2"
    args = gateware.build_license_docker_args({"LM_LICENSE_FILE": value})
    assert args == ["-e", f"LM_LICENSE_FILE={value}"]
    assert "-v" not in args


def test_floating_symbolic_port_name(gateware):
    """Case 6: `port_num@host` — port as a symbolic name, not numeric."""
    args = gateware.build_license_docker_args({"LM_LICENSE_FILE": "port_num@host"})
    assert args == ["-e", "LM_LICENSE_FILE=port_num@host"]
    assert "-v" not in args


# ---------------------------------------------------------------------------
# Unset / empty mode
# ---------------------------------------------------------------------------


def test_unset_raises_license_unset_error(gateware):
    """Case 8: env missing the key entirely -> LicenseUnsetError."""
    with pytest.raises(gateware.LicenseUnsetError) as excinfo:
        gateware.build_license_docker_args({})

    msg = str(excinfo.value)
    assert "LM_LICENSE_FILE" in msg


def test_empty_string_raises_license_unset_error(gateware):
    """Case 9: empty string is treated identically to unset."""
    with pytest.raises(gateware.LicenseUnsetError) as excinfo:
        gateware.build_license_docker_args({"LM_LICENSE_FILE": ""})

    msg = str(excinfo.value)
    assert "LM_LICENSE_FILE" in msg


def test_license_unset_error_is_runtime_error(gateware):
    """The exception class must subclass RuntimeError per AC-5."""
    assert issubclass(gateware.LicenseUnsetError, RuntimeError)


# ---------------------------------------------------------------------------
# Adversarial: whitespace / newline-laden values
# ---------------------------------------------------------------------------


def test_whitespace_only_value_does_not_classify_as_floating(gateware, tmp_path):
    """Adversarial: '   ' contains \\s so the regex rejects it as floating.

    AC-5 doesn't say what the helper does with a whitespace-only string that's
    also not a valid path. The most defensible behavior is that
    ``Path("   ").resolve(strict=True)`` raises FileNotFoundError (since no
    such file exists in any cwd). We just assert it does NOT return the
    floating-mode (-e only) shape, since the regex's \\s class rules out
    whitespace.
    """
    with pytest.raises(FileNotFoundError):
        gateware.build_license_docker_args({"LM_LICENSE_FILE": "   "})


def test_value_with_embedded_newline_does_not_classify_as_floating(gateware):
    """Adversarial: '27000@host\\n' contains \\s, so the regex rejects floating.

    With no '/' it's also not obviously a path. The strict path resolve will
    fail since the literal "27000@host\\n" file doesn't exist. We just lock in
    that the helper does NOT silently return floating-mode args (which would
    forward an environment variable containing a newline into the container —
    a security smell).
    """
    with pytest.raises(
        (FileNotFoundError, gateware.LicenseUnsetError, ValueError, OSError)
    ):
        gateware.build_license_docker_args({"LM_LICENSE_FILE": "27000@host\n"})


# ---------------------------------------------------------------------------
# Helper purity: respects injected Mapping (does not read os.environ).
# ---------------------------------------------------------------------------


def test_helper_reads_from_passed_mapping_not_process_env(
    gateware, monkeypatch, tmp_path
):
    """The helper must not fall back to os.environ when the Mapping lacks the key."""
    # Set the process env to a value that, if leaked, would force a path-mode
    # resolution attempt against /etc/lattice/license.dat (almost certainly
    # absent on the test host) — i.e., a different code path from the empty
    # Mapping the test passes in.
    monkeypatch.setenv("LM_LICENSE_FILE", "/etc/lattice/license.dat")

    # Pass an empty Mapping; the helper must use that, not os.environ.
    with pytest.raises(gateware.LicenseUnsetError):
        gateware.build_license_docker_args({})
