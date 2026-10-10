"""`synapsectl file get` must ask before replacing a local file."""

import argparse

from synapse.api.files_pb2 import ReadFileResponse
from synapse.cli import files as files_cli


class _FakeRpc:
    def __init__(self):
        self.read_requests = []

    def ListFiles(self, request):
        from synapse.api.files_pb2 import ListFilesResponse

        return ListFilesResponse(files=[ListFilesResponse.File(path="a.h5", size=6)])

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

    class _InterruptingRpc(_FakeRpc):
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


def test_ls_hides_dotfiles_unless_all(monkeypatch):
    from synapse.api.files_pb2 import ListFilesResponse

    printed = []
    monkeypatch.setattr(files_cli, "_print_file_list", lambda entries, console: printed.append([f.path for f in entries]))

    class _Rpc:
        def ListFiles(self, request):
            F = ListFilesResponse.File
            return ListFilesResponse(files=[
                F(path="rec/a.h5"), F(path="rec/.scifi-checked"), F(path="rec/.cache", is_dir=True),
                F(path="rec/.cache/x"),
            ])

    device = _FakeDevice()
    device.rpc = _Rpc()
    monkeypatch.setattr(files_cli, "Device", lambda *a, **k: device)
    base = dict(uri="x", verbose=False, path="rec", recursive=True, username=None, env_file=None, forget_password=False)

    files_cli.ls(argparse.Namespace(**base, all=False))
    files_cli.ls(argparse.Namespace(**base, all=True))

    assert printed[0] == ["rec/a.h5"]
    assert len(printed[1]) == 4


def test_listing_a_hidden_directory_by_name_shows_its_contents():
    assert not files_cli._is_hidden(".cache/x", ".cache")
    assert files_cli._is_hidden(".cache/x", "")


def _get_missing(monkeypatch, tmp_path, listing):
    import pytest
    from synapse.api.files_pb2 import ListFilesResponse

    class _Rpc(_FakeRpc):
        def ListFiles(self, request):
            return ListFilesResponse(files=listing)

    device = _FakeDevice()
    device.rpc = _Rpc()
    monkeypatch.setattr(files_cli, "Device", lambda *a, **k: device)
    args = argparse.Namespace(
        uri="x", verbose=False, remote_path="a.h5", output_path=str(tmp_path),
        recursive=False, no_resume=False, yes=False,
        username=None, env_file=None, forget_password=False,
    )
    with pytest.raises(SystemExit) as exit_info:
        files_cli.get(args)
    return device, exit_info.value.code


def test_get_of_a_missing_file_says_so_and_touches_nothing(monkeypatch, tmp_path, capsys):
    device, code = _get_missing(monkeypatch, tmp_path, listing=[])
    assert code == 1
    assert "a.h5 does not exist on the device" in capsys.readouterr().out
    assert device.rpc.read_requests == []
    assert list(tmp_path.iterdir()) == []


def test_get_of_a_directory_points_at_recursive(monkeypatch, tmp_path, capsys):
    from synapse.api.files_pb2 import ListFilesResponse

    _, code = _get_missing(monkeypatch, tmp_path, listing=[ListFilesResponse.File(path="a.h5", is_dir=True)])
    assert code == 1
    assert "--recursive" in capsys.readouterr().out
