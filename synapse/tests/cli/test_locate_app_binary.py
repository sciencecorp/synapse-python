"""Tests for ``locate_app_binary``, the pure-Python replacement for the
``find <app_dir> -type f -name <app_name> -not -path '*/.*'`` shell-out.

The behavioral tests below encode the old ``find`` invocation's semantics so
they run on every platform (including Windows, where ``find`` is a different
program entirely). ``test_parity_with_gnu_find`` additionally runs the real
``find`` command side by side on POSIX hosts to demonstrate identical
functionality against the original implementation.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from synapse.cli.build import locate_app_binary


APP = "myapp"


def _touch(*parts):
    path = os.path.join(*[str(p) for p in parts])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("bin")
    return path


def test_finds_binary_in_nested_build_dir(tmp_path):
    expected = _touch(tmp_path, "build", "aarch64", "release", APP)
    assert locate_app_binary(str(tmp_path), APP) == expected


def test_returns_none_when_absent(tmp_path):
    _touch(tmp_path, "build", "other-binary")
    assert locate_app_binary(str(tmp_path), APP) is None


def test_hidden_directories_are_skipped(tmp_path):
    # A match buried under a hidden dir (e.g. .git) must not win over a
    # visible one -- and must not be returned at all.
    _touch(tmp_path, ".git", "objects", APP)
    visible = _touch(tmp_path, "build", APP)
    assert locate_app_binary(str(tmp_path), APP) == visible


def test_match_only_under_hidden_directory_returns_none(tmp_path):
    _touch(tmp_path, ".cache", APP)
    assert locate_app_binary(str(tmp_path), APP) is None


def test_exact_name_match_only(tmp_path):
    _touch(tmp_path, "build", APP + ".o")
    _touch(tmp_path, "build", "lib" + APP)
    assert locate_app_binary(str(tmp_path), APP) is None


def test_directory_with_matching_name_is_not_a_match(tmp_path):
    # `find -type f` never matches directories.
    os.makedirs(os.path.join(str(tmp_path), "build", APP))
    assert locate_app_binary(str(tmp_path), APP) is None


def test_hidden_app_name_returns_none(tmp_path):
    # `-not -path '*/.*'` also excluded hidden *files*.
    _touch(tmp_path, "build", ".hidden")
    assert locate_app_binary(str(tmp_path), ".hidden") is None


def test_root_level_match_wins_over_nested(tmp_path):
    # os.walk yields the walk root first, so a top-level match is returned
    # before any nested one. (With multiple matches the old `find` contract
    # was only ever "some match" -- its first output line -- and the caller
    # copies whichever match is returned to the canonical location.)
    root_match = _touch(tmp_path, APP)
    _touch(tmp_path, "build", APP)
    assert locate_app_binary(str(tmp_path), APP) == root_match


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX `find` is not available on Windows"
)
@pytest.mark.parametrize(
    "layout",
    [
        [],  # empty tree
        ["build/aarch64/" + APP],  # the common case
        [".git/" + APP],  # only a hidden match
        ["a/" + APP, "b/" + APP, APP],  # multiple matches
        ["build/" + APP + ".dbg", "docs/readme"],  # near-misses only
    ],
)
def test_parity_with_gnu_find(tmp_path, layout):
    """The exact `find` argv that locate_app_binary replaced is run against the same tree to verify identical behavior."""
    for rel in layout:
        _touch(tmp_path, *rel.split("/"))

    find_out = subprocess.run(
        ["find", str(tmp_path), "-type", "f", "-name", APP,
         "-not", "-path", "*/.*"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    find_matches = find_out.split("\n") if find_out else []

    result = locate_app_binary(str(tmp_path), APP)

    if not find_matches:
        assert result is None
    else:
        assert result in find_matches
