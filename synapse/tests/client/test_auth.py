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

    # The device was renamed on a later pairing; the serial (and token) are
    # unchanged, so the lookup must still work, and the stored hint must be
    # the new name, not the stale one.
    auth.save_token("NYX1512-0042", "new-name", "f3a9c1")

    assert auth.token_for_serial("NYX1512-0042") == "f3a9c1"
    assert auth.load_tokens()["NYX1512-0042"] == ("new-name", "f3a9c1")


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


def test_no_temp_file_left_behind_after_save(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    leftovers = [p.name for p in env_file.parent.iterdir() if p != env_file]
    assert leftovers == []


def test_failed_write_leaves_original_file_intact(env_file):
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permission checks")

    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")
    original = env_file.read_bytes()

    # Strip write permission on the directory so the temp file used for the
    # atomic replace cannot even be created; the original must survive.
    env_file.parent.chmod(0o500)
    try:
        with pytest.raises(OSError):
            auth.save_token("NYX1512-0099", "sci-fi-9999", "token-b")
    finally:
        env_file.parent.chmod(0o700)

    assert env_file.read_bytes() == original


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


def test_open_methods_are_not_gated():
    for name in ("Info", "GetLogs", "TailLogs", "RequestAuth"):
        assert f"/synapse.SynapseDevice/{name}" in auth.OPEN_METHODS


def test_closed_methods_are_not_in_the_open_set():
    for name in ("Configure", "Start", "Stop", "Query", "StreamQuery"):
        assert f"/synapse.SynapseDevice/{name}" not in auth.OPEN_METHODS


class _FakeCallDetails:
    def __init__(self, method):
        self.method = method
        self.timeout = None
        self.metadata = None
        self.credentials = None
        self.wait_for_ready = None
        self.compression = None


def test_interceptor_sends_no_metadata_for_open_methods(env_file, monkeypatch):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    # Resolution would need a network call; if it happens for an open method,
    # this raises and the test fails.
    def explode(_channel):
        raise AssertionError("resolved the serial for an open method")

    interceptor = auth.AuthInterceptor(serial_resolver=explode)
    seen = {}

    def continuation(details, request):
        seen["metadata"] = details.metadata
        return "response"

    result = interceptor.intercept_unary_unary(
        continuation, _FakeCallDetails("/synapse.SynapseDevice/Info"), object()
    )

    assert result == "response"
    assert not seen["metadata"]


def test_interceptor_attaches_token_for_closed_methods(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    interceptor = auth.AuthInterceptor(serial_resolver=lambda _c: "NYX1512-0042")
    seen = {}

    def continuation(details, request):
        seen["metadata"] = dict(details.metadata or [])
        return "response"

    interceptor.intercept_unary_unary(
        continuation, _FakeCallDetails("/synapse.SynapseDevice/Configure"), object()
    )

    assert seen["metadata"]["authorization"] == "Bearer f3a9c1"


def test_interceptor_skips_resolution_when_no_tokens_exist(env_file):
    def explode(_channel):
        raise AssertionError("resolved the serial with an empty env file")

    interceptor = auth.AuthInterceptor(serial_resolver=explode)
    seen = {}

    def continuation(details, request):
        seen["metadata"] = details.metadata
        return "response"

    interceptor.intercept_unary_unary(
        continuation, _FakeCallDetails("/synapse.SynapseDevice/Configure"), object()
    )

    assert not seen["metadata"]


def test_interceptor_resolves_only_once_per_channel(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    calls = []

    def counting_resolver(_channel):
        calls.append(1)
        return "NYX1512-0042"

    interceptor = auth.AuthInterceptor(serial_resolver=counting_resolver)

    def continuation(details, request):
        return "response"

    for _ in range(3):
        interceptor.intercept_unary_unary(
            continuation, _FakeCallDetails("/synapse.SynapseDevice/Configure"), object()
        )

    assert len(calls) == 1


def test_unknown_serial_sends_no_token(env_file):
    auth.save_token("NYX1512-0042", "sci-fi-1234", "f3a9c1")

    interceptor = auth.AuthInterceptor(serial_resolver=lambda _c: "SOME-OTHER-SERIAL")
    seen = {}

    def continuation(details, request):
        seen["metadata"] = details.metadata
        return "response"

    interceptor.intercept_unary_unary(
        continuation, _FakeCallDetails("/synapse.SynapseDevice/Configure"), object()
    )

    # No token for that serial: send nothing and let the server explain.
    assert not seen["metadata"]
