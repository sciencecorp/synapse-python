"""Tests for the gRPC file client.

The device is faked: these pin the client's side of the contract -- chunking,
the path-first upload framing, and resume -- which is where the bugs that only
show up on multi-gigabyte files would live.
"""

import os

import pytest

from synapse.api.files_pb2 import ListFilesResponse, ReadFileResponse, WriteFileResponse
from synapse.client import files as files_client


class _FakeRpc:
    def __init__(self, read_chunks=None, listing=None):
        self._read_chunks = read_chunks or []
        self._listing = listing or []
        self.written = bytearray()
        self.upload_messages = []
        self.read_requests = []

    def ListFiles(self, request):
        self.list_request = request
        return ListFilesResponse(files=self._listing)

    def ReadFile(self, request):
        self.read_requests.append(request)
        return iter(self._read_chunks)

    def WriteFile(self, message_iter):
        for m in message_iter:
            self.upload_messages.append(m)
            self.written.extend(m.data)
        return WriteFileResponse(path="x", bytes_written=len(self.written))

    def DeleteFile(self, request):
        self.delete_request = request
        return None


class _FakeDevice:
    def __init__(self, **kw):
        self.rpc = _FakeRpc(**kw)


def test_upload_sends_the_path_first_and_then_chunks(tmp_path):
    # The server resolves and opens the target from the first message, so a
    # first message carrying data-but-no-path would have nowhere to write.
    src = tmp_path / "big.bin"
    src.write_bytes(b"a" * (files_client.CHUNK_BYTES + 17))

    device = _FakeDevice()
    written = files_client.write_file(device, str(src), "run_1/big.bin")

    msgs = device.rpc.upload_messages
    assert msgs[0].path == "run_1/big.bin"
    assert msgs[0].data == b""
    assert all(m.path == "" for m in msgs[1:]), "path must not repeat on every chunk"
    assert len(msgs) == 3, "expected path + 2 chunks"
    assert bytes(device.rpc.written) == src.read_bytes()
    assert written == src.stat().st_size


def test_upload_chunks_stay_under_the_grpc_message_limit(tmp_path):
    # The whole reason WriteFile is client-streaming: a 4 MB default message
    # limit makes a one-shot upload impossible for real recordings.
    src = tmp_path / "x.bin"
    src.write_bytes(b"b" * (5 * 1024 * 1024))
    device = _FakeDevice()
    files_client.write_file(device, str(src), "x.bin")
    assert all(len(m.data) <= files_client.CHUNK_BYTES for m in device.rpc.upload_messages)


def test_download_writes_every_chunk_in_order(tmp_path):
    chunks = [
        ReadFileResponse(path="f", data=b"hello ", start_offset=0, file_total_length=11),
        ReadFileResponse(path="f", data=b"world", start_offset=6, file_total_length=11),
    ]
    device = _FakeDevice(read_chunks=chunks)
    dest = tmp_path / "out" / "f"
    n = files_client.read_file(device, "f", str(dest), resume=False)
    assert dest.read_bytes() == b"hello world"
    assert n == 11


def test_download_resumes_from_what_is_already_on_disk(tmp_path):
    # A 3 GB recording that dies at 90% must not start over.
    dest = tmp_path / "f"
    dest.write_bytes(b"hello ")
    chunks = [ReadFileResponse(path="f", data=b"world", start_offset=6, file_total_length=11)]
    device = _FakeDevice(read_chunks=chunks)

    n = files_client.read_file(device, "f", str(dest))

    assert device.rpc.read_requests[0].start_offset == 6, "did not ask to resume"
    assert dest.read_bytes() == b"hello world"
    assert n == 11


def test_resume_false_refetches_from_the_start(tmp_path):
    dest = tmp_path / "f"
    dest.write_bytes(b"stale")
    chunks = [ReadFileResponse(path="f", data=b"fresh", start_offset=0, file_total_length=5)]
    device = _FakeDevice(read_chunks=chunks)
    files_client.read_file(device, "f", str(dest), resume=False)
    assert device.rpc.read_requests[0].start_offset == 0
    assert dest.read_bytes() == b"fresh"


def test_empty_file_still_creates_the_local_file(tmp_path):
    device = _FakeDevice(read_chunks=[])
    dest = tmp_path / "empty"
    assert files_client.read_file(device, "empty", str(dest), resume=False) == 0
    assert dest.exists()


def test_delete_passes_recursive_through(tmp_path):
    device = _FakeDevice()
    files_client.delete_file(device, "run_1", recursive=True)
    assert device.rpc.delete_request.recursive is True
    assert device.rpc.delete_request.path == "run_1"


def test_upload_into_a_directory_appends_the_basename(tmp_path, monkeypatch):
    """`put file some/dir` must mean into that directory.

    The bug: uploading to an existing directory transferred the whole file and
    then failed at the final rename, because the server cannot replace a
    directory with a file. 194 MB were sent before the error appeared.
    """
    from synapse.api.files_pb2 import ListFilesResponse
    from synapse.cli import files as cli

    src = tmp_path / "recording.h5"
    src.write_bytes(b"data")

    listing = [ListFilesResponse.File(path="hdf5-replay", size=0, is_dir=True)]
    device = _FakeDevice(listing=listing)

    assert cli._remote_is_dir(device, "hdf5-replay") is True

    captured = {}

    def fake_upload(dev, console, local, remote):
        captured["remote"] = remote
        return 4

    monkeypatch.setattr(cli, "_upload_one", fake_upload)

    class Args:
        uri = "1.2.3.4"
        verbose = False
        local_path = str(src)
        remote_path = "hdf5-replay"
        recursive = False

    monkeypatch.setattr(cli, "Device", lambda uri, verbose: device)
    cli.put(Args())

    assert captured["remote"] == "hdf5-replay/recording.h5"


def test_upload_to_a_plain_path_is_left_alone(tmp_path, monkeypatch):
    from synapse.cli import files as cli

    src = tmp_path / "x.bin"
    src.write_bytes(b"y")
    device = _FakeDevice(listing=[])

    captured = {}
    monkeypatch.setattr(cli, "_upload_one", lambda d, c, l, r: captured.setdefault("remote", r))
    monkeypatch.setattr(cli, "Device", lambda uri, verbose: device)

    class Args:
        uri = "1.2.3.4"
        verbose = False
        local_path = str(src)
        remote_path = "dump/explicit.bin"
        recursive = False

    cli.put(Args())
    assert captured["remote"] == "dump/explicit.bin"
