"""`synapsectl file get` must ask before replacing a local file."""

import argparse

from synapse.api.files_pb2 import ReadFileResponse
from synapse.cli import files as files_cli


class _FakeRpc:
    def __init__(self):
        self.read_requests = []

    def ReadFile(self, request):
        self.read_requests.append(request)
        return iter([ReadFileResponse(path="a.h5", data=b"remote", file_total_length=6)])


class _FakeDevice:
    def __init__(self, *args, **kwargs):
        self.rpc = _FakeRpc()


def _get(monkeypatch, tmp_path, answer, yes=False):
    device = _FakeDevice()
    monkeypatch.setattr(files_cli, "Device", lambda *a, **k: device)
    monkeypatch.setattr(files_cli.Confirm, "ask", lambda *a, **k: answer)
    args = argparse.Namespace(
        uri="x", verbose=False, remote_path="a.h5", output_path=str(tmp_path),
        recursive=False, no_resume=False, yes=yes,
        username=None, env_file=None, forget_password=False,
    )
    files_cli.get(args)
    return device


def test_declining_the_prompt_leaves_the_local_file_and_fetches_nothing(monkeypatch, tmp_path):
    (tmp_path / "a.h5").write_bytes(b"mine")
    device = _get(monkeypatch, tmp_path, answer=False)
    assert device.rpc.read_requests == []
    assert (tmp_path / "a.h5").read_bytes() == b"mine"


def test_accepting_the_prompt_replaces_the_local_file(monkeypatch, tmp_path):
    (tmp_path / "a.h5").write_bytes(b"mine")
    _get(monkeypatch, tmp_path, answer=True)
    assert (tmp_path / "a.h5").read_bytes() == b"remote"


def test_yes_overwrites_without_asking(monkeypatch, tmp_path):
    (tmp_path / "a.h5").write_bytes(b"mine")
    _get(monkeypatch, tmp_path, answer=False, yes=True)  # would decline, if it were asked
    assert (tmp_path / "a.h5").read_bytes() == b"remote"


class _FakePutRpc:
    """A device holding `a.h5` at its data root."""

    def __init__(self):
        self.uploads = []

    def ListFiles(self, request):
        from synapse.api.files_pb2 import ListFilesResponse

        return ListFilesResponse(files=[ListFilesResponse.File(path="a.h5", size=4)])

    def WriteFile(self, messages):
        from synapse.api.files_pb2 import WriteFileResponse

        msgs = list(messages)
        self.uploads.append(msgs[0].path)
        return WriteFileResponse(path=msgs[0].path, bytes_written=sum(len(m.data) for m in msgs))


def _put(monkeypatch, tmp_path, answer, yes=False, remote=None):
    device = _FakeDevice()
    device.rpc = _FakePutRpc()
    monkeypatch.setattr(files_cli, "Device", lambda *a, **k: device)
    monkeypatch.setattr(files_cli.Confirm, "ask", lambda *a, **k: answer)
    src = tmp_path / "a.h5"
    src.write_bytes(b"mine")
    args = argparse.Namespace(
        uri="x", verbose=False, local_path=str(src), remote_path=remote, recursive=False, yes=yes
    )
    files_cli.put(args)
    return device.rpc.uploads


def test_put_declined_does_not_upload_over_a_device_file(monkeypatch, tmp_path):
    assert _put(monkeypatch, tmp_path, answer=False) == []


def test_put_accepted_or_yes_uploads_over_a_device_file(monkeypatch, tmp_path):
    assert _put(monkeypatch, tmp_path, answer=True) == ["a.h5"]
    assert _put(monkeypatch, tmp_path, answer=False, yes=True) == ["a.h5"]


def test_put_to_a_new_name_does_not_ask(monkeypatch, tmp_path):
    assert _put(monkeypatch, tmp_path, answer=False, remote="b.h5") == ["b.h5"]


def test_an_interrupted_get_says_where_the_partial_is(monkeypatch, tmp_path, capsys):
    import pytest

    class _InterruptingRpc:
        def ReadFile(self, request):
            yield ReadFileResponse(path="a.h5", data=b"half", file_total_length=8)
            raise KeyboardInterrupt

    device = _FakeDevice()
    device.rpc = _InterruptingRpc()
    monkeypatch.setattr(files_cli, "Device", lambda *a, **k: device)
    args = argparse.Namespace(
        uri="x", verbose=False, remote_path="a.h5", output_path=str(tmp_path),
        recursive=False, no_resume=False, yes=False,
        username=None, env_file=None, forget_password=False,
    )
    with pytest.raises(SystemExit):
        files_cli.get(args)

    out = capsys.readouterr().out
    assert "a.h5.partial" in out and "resume" in out
    assert (tmp_path / "a.h5.partial").read_bytes() == b"half"
