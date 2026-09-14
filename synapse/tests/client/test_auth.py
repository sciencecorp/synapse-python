import logging
import os
import stat

import pytest

from synapse.client import auth

logger = logging.getLogger(__name__)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".scifi-env"
    monkeypatch.setenv("SCIFI_ENV_FILE", str(path))
    return path


def test_missing_file_yields_no_tokens(env_file):
    assert auth.load_tokens() == {}
    assert auth.token_for_serial("NYX1512-0042") is None
    assert auth.has_any_tokens() is False


def test_saved_token_round_trips(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    assert auth.token_for_serial("NYX1512-0042") == "f3a9c1"
    assert auth.has_any_tokens() is True
    assert auth.load_tokens() == {"NYX1512-0042": ("sci-fi-1234", "f3a9c1")}


def test_renamed_device_still_matches_by_serial(env_file):
    auth.save_token("NYX1512-0042", "old-name", "f3a9c1")

    # The device was renamed; the serial is unchanged, so the token still works.
    assert auth.token_for_serial("NYX1512-0042") == "f3a9c1"


def test_saving_the_same_serial_replaces_the_entry(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "old-token")
    auth.save_token("NYX1512-0042", "renamed", "new-token")

    tokens = auth.load_tokens()
    assert len(tokens) == 1
    assert tokens["NYX1512-0042"] == ("renamed", "new-token")


def test_multiple_devices_coexist(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "token-a")
    auth.save_token("NYX1512-0099", "sci-fi-9999", "token-b")

    assert auth.token_for_serial("NYX1512-0042") == "token-a"
    assert auth.token_for_serial("NYX1512-0099") == "token-b"


def test_file_is_owner_only(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    mode = stat.S_IMODE(os.stat(env_file).st_mode)
    assert mode == 0o600


def test_comments_and_blank_lines_are_ignored(env_file):
    env_file.write_text(
        "# serial            name           token\n"
        "\n"
        "NYX1512-0042        sci-fi-1234    f3a9c1\n"
    )

    assert auth.token_for_serial("NYX1512-0042") == "f3a9c1"


def test_malformed_lines_are_skipped_not_fatal(env_file):
    env_file.write_text(
        "this-line-has-only-one-field\n"
        "NYX1512-0042        sci-fi-1234    f3a9c1\n"
    )

    assert auth.token_for_serial("NYX1512-0042") == "f3a9c1"


def test_remove_token(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    assert auth.remove_token("NYX1512-0042") is True
    assert auth.token_for_serial("NYX1512-0042") is None
    assert auth.remove_token("NYX1512-0042") is False


def test_env_override_is_honored(tmp_path, monkeypatch):
    custom = tmp_path / "custom-env"
    monkeypatch.setenv("SCIFI_ENV_FILE", str(custom))

    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    assert custom.exists()
