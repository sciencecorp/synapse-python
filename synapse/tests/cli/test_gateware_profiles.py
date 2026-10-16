"""Per-profile gateware project resolution.

A peripheral repo may ship its gateware in one of two layouts:

* **single-project** — ``src/gateware/peripheral.yaml``, the original shape;
* **per-profile** — ``src/gateware/<profile>/peripheral.yaml``, one SDK project
  per target profile (``via-devkit``, ``nerv512u-devkit``, …).

The second layout exists because a profile's generated top wrapper, seed
constraints, and encrypted transport bundle collide by filename with any other
profile's while differing in content, so they cannot share a directory.

``resolve_gateware_project`` is the single place that decides which project a
command acts on. These tests pin its contract, especially the refusal to guess
when a repo has several profiles: an arbitrary pick would silently build a
driver whose compiled-in clock rate belongs to the other devkit.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def gw():
    return importlib.import_module("synapse.cli.gateware")


def _make_repo(root, *, single=False, profiles=()):
    """Materialise a peripheral repo with the requested gateware layout."""
    gateware_root = root / "src" / "gateware"
    gateware_root.mkdir(parents=True, exist_ok=True)
    if single:
        (gateware_root / "peripheral.yaml").write_text("schema_version: 1\n")
    for name in profiles:
        profile_dir = gateware_root / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "peripheral.yaml").write_text(
            f"schema_version: 1\ntarget_profile: {name}\n"
        )
    return root


# ---------------------------------------------------------------------------
# discover_gateware_profiles
# ---------------------------------------------------------------------------


def test_discover_returns_sorted_profile_names(gw, tmp_path):
    _make_repo(tmp_path, profiles=("nerv512u-devkit", "via-devkit"))
    assert gw.discover_gateware_profiles(str(tmp_path)) == [
        "nerv512u-devkit",
        "via-devkit",
    ]


def test_discover_ignores_dirs_without_a_manifest(gw, tmp_path):
    """``build/`` and other scratch dirs must not read as profile projects."""
    _make_repo(tmp_path, profiles=("via-devkit",))
    (tmp_path / "src" / "gateware" / "build").mkdir()
    (tmp_path / "src" / "gateware" / "build" / "bitstreams").mkdir()
    assert gw.discover_gateware_profiles(str(tmp_path)) == ["via-devkit"]


def test_discover_on_missing_gateware_root_is_empty(gw, tmp_path):
    assert gw.discover_gateware_profiles(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# resolve_gateware_project
# ---------------------------------------------------------------------------


def test_single_project_layout_resolves_without_a_profile(gw, tmp_path):
    """The pre-multi-profile layout keeps working with no flag and no env."""
    _make_repo(tmp_path, single=True)
    assert gw.resolve_gateware_project(str(tmp_path), None, {}) == "src/gateware"


def test_lone_profile_resolves_without_a_profile(gw, tmp_path):
    """One profile is unambiguous, so requiring --profile would be noise."""
    _make_repo(tmp_path, profiles=("nerv512u-devkit",))
    assert (
        gw.resolve_gateware_project(str(tmp_path), None, {})
        == "src/gateware/nerv512u-devkit"
    )


def test_explicit_profile_selects_that_project(gw, tmp_path):
    _make_repo(tmp_path, profiles=("nerv512u-devkit", "via-devkit"))
    assert (
        gw.resolve_gateware_project(str(tmp_path), "via-devkit", {})
        == "src/gateware/via-devkit"
    )


def test_env_var_selects_when_no_explicit_profile(gw, tmp_path):
    _make_repo(tmp_path, profiles=("nerv512u-devkit", "via-devkit"))
    env = {gw.PROFILE_ENV_VAR: "nerv512u-devkit"}
    assert (
        gw.resolve_gateware_project(str(tmp_path), None, env)
        == "src/gateware/nerv512u-devkit"
    )


def test_explicit_profile_beats_env_var(gw, tmp_path):
    _make_repo(tmp_path, profiles=("nerv512u-devkit", "via-devkit"))
    env = {gw.PROFILE_ENV_VAR: "nerv512u-devkit"}
    assert (
        gw.resolve_gateware_project(str(tmp_path), "via-devkit", env)
        == "src/gateware/via-devkit"
    )


def test_explicit_profile_wins_over_a_single_project_root(gw, tmp_path):
    """A repo mid-migration (root manifest + profile dirs) honours the flag."""
    _make_repo(tmp_path, single=True, profiles=("via-devkit",))
    assert (
        gw.resolve_gateware_project(str(tmp_path), "via-devkit", {})
        == "src/gateware/via-devkit"
    )


def test_ambiguous_repo_refuses_to_guess(gw, tmp_path):
    """Two profiles and no selection must raise, never pick one."""
    _make_repo(tmp_path, profiles=("nerv512u-devkit", "via-devkit"))
    with pytest.raises(gw.GatewareProfileError) as exc:
        gw.resolve_gateware_project(str(tmp_path), None, {})
    message = str(exc.value)
    assert "--profile" in message
    # The error has to name the candidates, or the user has to go look.
    assert "via-devkit" in message and "nerv512u-devkit" in message


def test_unknown_profile_raises_and_lists_available(gw, tmp_path):
    _make_repo(tmp_path, profiles=("nerv512u-devkit", "via-devkit"))
    with pytest.raises(gw.GatewareProfileError) as exc:
        gw.resolve_gateware_project(str(tmp_path), "sciop-devkit", {})
    message = str(exc.value)
    assert "sciop-devkit" in message
    assert "via-devkit" in message and "nerv512u-devkit" in message


def test_no_gateware_project_at_all_raises(gw, tmp_path):
    with pytest.raises(gw.GatewareProfileError) as exc:
        gw.resolve_gateware_project(str(tmp_path), None, {})
    assert "No gateware project found" in str(exc.value)


def test_bare_gateware_dir_without_manifest_raises(gw, tmp_path):
    """An empty src/gateware/ is not a project. (The pass-through treats this
    as the scaffolding case and redirects anyway; resolution itself still
    reports that there is nothing to build.)"""
    (tmp_path / "src" / "gateware").mkdir(parents=True)
    with pytest.raises(gw.GatewareProfileError):
        gw.resolve_gateware_project(str(tmp_path), None, {})


# ---------------------------------------------------------------------------
# run_gateware_build honours the resolved project
# ---------------------------------------------------------------------------


def test_build_command_and_bit_glob_follow_the_project_subdir(
    gw, tmp_path, monkeypatch
):
    """The SDK ``--project`` argument and the bitstream glob must agree; a
    mismatch would build one profile and package the other's stale .bit."""
    project = "src/gateware/via-devkit"
    bitstreams = tmp_path / project / "build" / "bitstreams"
    bitstreams.mkdir(parents=True)
    expected_bit = bitstreams / "sdk_via-devkit_gateware_extracted.bit"
    expected_bit.write_bytes(b"\x00")

    # A decoy under the *other* profile proves the glob is scoped.
    other = tmp_path / "src/gateware/nerv512u-devkit/build/bitstreams"
    other.mkdir(parents=True)
    (other / "sdk_nerv512u-devkit_gateware_extracted.bit").write_bytes(b"\x00")

    recorded = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        import subprocess as sp

        return sp.CompletedProcess(argv, 0)

    monkeypatch.setattr(gw.subprocess, "run", fake_run)

    got = gw.run_gateware_build(
        str(tmp_path),
        "fake-gw:latest",
        env={"LM_LICENSE_FILE": "7788@licenseserver"},
        project_subdir=project,
    )

    assert got == str(expected_bit)
    assert f"axon-peripheral-sdk build --project {project}" in recorded["argv"][-1]
