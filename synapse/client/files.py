"""File transfer over gRPC.

Replaces SFTP as the transport for device files. The point is not convenience:
SFTP needed its own password, so a device carried two independent credentials.
Going through the SynapseDevice service means file access is governed by the
same pairing token as everything else, and the SFTP password disappears.

Paths are relative to the device's data root and cannot escape it. That is the
same tree the scifi-sftp account was chrooted to, so reach is unchanged -- what
goes away is the second credential.
"""

import os
from typing import Callable, Iterator, List, Optional

from synapse.api.files_pb2 import (
    DeleteFileRequest,
    ListFilesRequest,
    ListFilesResponse,
    ReadFileRequest,
    WriteFileRequest,
)

# Chunk size for uploads. Well under gRPC's 4 MB default message limit, leaving
# room for the message's other fields.
CHUNK_BYTES = 1 << 20  # 1 MiB

ProgressFn = Callable[[int, int], None]


def list_files(device, path: str = "", recursive: bool = False) -> List[ListFilesResponse.File]:
    return list(device.rpc.ListFiles(ListFilesRequest(path=path, recursive=recursive)).files)


def read_file(
    device,
    remote_path: str,
    local_path: str,
    progress: Optional[ProgressFn] = None,
    resume: bool = True,
) -> int:
    """Download `remote_path` to `local_path`, returning bytes written.

    Resumes from whatever is already on disk by default: a multi-gigabyte
    recording that dies at 90% should not have to start over. Set resume=False
    to always fetch from the beginning.
    """
    start_offset = 0
    if resume and os.path.exists(local_path):
        start_offset = os.path.getsize(local_path)

    stream = device.rpc.ReadFile(
        ReadFileRequest(path=remote_path, start_offset=start_offset)
    )

    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    written = start_offset
    mode = "r+b" if start_offset else "wb"
    # Open lazily inside the loop's first iteration would be tidier, but the
    # server may legitimately send zero chunks (an empty file), and the file
    # still has to exist afterwards.
    with open(local_path, mode) as f:
        if start_offset:
            f.seek(start_offset)
        for chunk in stream:
            f.write(chunk.data)
            written += len(chunk.data)
            if progress:
                progress(written, chunk.file_total_length)
    return written


def _upload_messages(remote_path: str, local_path: str, progress: Optional[ProgressFn]):
    """The request stream: path first, then chunks.

    The first message carries the path and no data, so the server can resolve
    and open the target before any bytes arrive.
    """
    total = os.path.getsize(local_path)
    yield WriteFileRequest(path=remote_path)
    sent = 0
    with open(local_path, "rb") as f:
        while True:
            data = f.read(CHUNK_BYTES)
            if not data:
                break
            sent += len(data)
            if progress:
                progress(sent, total)
            yield WriteFileRequest(data=data)


def write_file(
    device, local_path: str, remote_path: str, progress: Optional[ProgressFn] = None
) -> int:
    """Upload `local_path` to `remote_path`, returning bytes the device wrote."""
    response = device.rpc.WriteFile(_upload_messages(remote_path, local_path, progress))
    return response.bytes_written


def delete_file(device, path: str, recursive: bool = False) -> None:
    device.rpc.DeleteFile(DeleteFileRequest(path=path, recursive=recursive))
