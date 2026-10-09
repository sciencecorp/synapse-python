"""Pairing tokens for SciFi devices.

A token is stored per device serial in a user-wide file (default
``$HOME/.scifi-env``, overridable with ``SCIFI_ENV_FILE``):

    # serial            name           token
    NYX1512-0042        sci-fi-1234    f3a9c1...

Keyed on serial rather than name because device names are neither unique nor
stable, and keying on a name means renaming a device silently orphans its token.
The name is kept as a human-readable hint only.

The file is not shell-sourceable: device names contain hyphens, so
``sci-fi-1234=...`` is not a valid shell variable, and mangling names into
``SCIFI_TOKEN_SCI_FI_1234`` risks two names colliding on one key.
"""

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import grpc

logger = logging.getLogger(__name__)

_HEADER = "# serial\tname\ttoken\n"


def env_file_path() -> Path:
    override = os.environ.get("SCIFI_ENV_FILE")
    if override:
        return Path(override)
    return Path.home() / ".scifi-env"


def load_tokens() -> Dict[str, Tuple[str, str]]:
    """Return {serial: (name, token)}. A missing or unreadable file is empty."""
    path = env_file_path()
    if not path.exists():
        return {}

    tokens: Dict[str, Tuple[str, str]] = {}
    try:
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 3:
                logger.debug("Skipping malformed line in %s: %r", path, line)
                continue
            serial, name, token = fields[0], fields[1], fields[2]
            tokens[serial] = (name, token)
    except OSError as e:
        logger.debug("Could not read %s: %s", path, e)
        return {}
    return tokens


def token_for_serial(serial: str) -> Optional[str]:
    entry = load_tokens().get(serial)
    return entry[1] if entry else None


def has_any_tokens() -> bool:
    return bool(load_tokens())


def save_token(serial: str, name: str, token: str) -> None:
    """Add or replace the entry for `serial`, leaving other devices untouched."""
    tokens = load_tokens()
    tokens[serial] = (name, token)
    _write(tokens)


def remove_token(serial: str) -> bool:
    """Drop the local entry. Returns False if there was nothing to drop."""
    tokens = load_tokens()
    if serial not in tokens:
        return False
    del tokens[serial]
    _write(tokens)
    return True


def _write(tokens: Dict[str, Tuple[str, str]]) -> None:
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [_HEADER]
    for serial, (name, token) in sorted(tokens.items()):
        lines.append(f"{serial}\t{name}\t{token}\n")

    # Write to a temp file in the same directory, then atomically swap it in
    # with os.replace(). A truncate-in-place rewrite can leave the file empty
    # or torn if the process dies mid-write (OOM kill, power loss, disk full),
    # losing every paired device's token, and offers no protection against two
    # concurrent writers interleaving bytes. os.replace() is atomic within a
    # filesystem, so a reader always sees either the complete old file or the
    # complete new one -- hence the temp file must live next to the target
    # (not /tmp, which may be a different mount than $HOME).
    #
    # mkstemp() creates the file with mode 0600 already (it does not consult
    # umask), but we chmod explicitly rather than rely on that, matching how
    # the final file is created 0600 from the outset, never briefly
    # world-readable, not even under the temp name.
    fd, tmp_path = tempfile.mkstemp(
        prefix=".scifi-env.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
            f.flush()
            # fsync before the replace: without it, the rename can be durable
            # while the file's contents are not, so a crash right after could
            # swap in a file that reads back empty.
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# The standard bearer-token header (RFC 6750) rather than a bespoke x- key, so
# proxies and tooling that already understand it keep working. The value carries
# the "Bearer " scheme; the server strips it case-insensitively.
METADATA_KEY = "authorization"
METADATA_SCHEME = "Bearer "

# Mirrors scifi-server's open set (src/auth/rpc_auth_policy.cpp). These need no
# token, so the interceptor never triggers serial resolution for them.
OPEN_METHODS = frozenset(
    {
        "/synapse.SynapseDevice/Info",
        "/synapse.SynapseDevice/GetLogs",
        "/synapse.SynapseDevice/TailLogs",
        "/synapse.SynapseDevice/RequestAuth",
    }
)


def resolve_serial_via_info(channel) -> Optional[str]:
    """One Info call to learn the device serial. Info is open, so no token."""
    from google.protobuf.empty_pb2 import Empty

    from synapse.api.synapse_pb2_grpc import SynapseDeviceStub

    try:
        info = SynapseDeviceStub(channel).Info(Empty(), timeout=5.0)
        return info.serial or None
    except grpc.RpcError as e:
        logger.debug("Could not read the device serial: %s", e)
        return None


class AuthInterceptor(
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamUnaryClientInterceptor,
    grpc.StreamStreamClientInterceptor,
):
    """Attaches the pairing token to calls that need one.

    Resolution is lazy and happens at most once per channel: the first call to a
    token-gated method learns the device serial, looks the token up, and caches
    it. Open methods never trigger it, so discovery and log tailing cost nothing
    extra, and neither does an unpaired user with no env file.
    """

    def __init__(self, channel=None, serial_resolver=None):
        self._channel = channel
        self._resolve = serial_resolver or resolve_serial_via_info
        self._lock = threading.Lock()
        self._resolved = False
        self._token: Optional[str] = None

    def _token_for_call(self) -> Optional[str]:
        with self._lock:
            if self._resolved:
                return self._token
            self._resolved = True

            if not has_any_tokens():
                # Nothing paired anywhere: do not pay for an Info call.
                return None

            serial = self._resolve(self._channel)
            if not serial:
                logger.debug("No device serial available; sending no token")
                return None

            self._token = token_for_serial(serial)
            if self._token is None:
                logger.debug("No token stored for serial %s", serial)
            return self._token

    def _with_token(self, call_details):
        if call_details.method in OPEN_METHODS:
            return call_details

        token = self._token_for_call()
        if not token:
            return call_details

        metadata = list(call_details.metadata or [])
        metadata.append((METADATA_KEY, f"{METADATA_SCHEME}{token}"))
        return _ClientCallDetails(call_details, metadata)

    def intercept_unary_unary(self, continuation, call_details, request):
        return continuation(self._with_token(call_details), request)

    def intercept_unary_stream(self, continuation, call_details, request):
        return continuation(self._with_token(call_details), request)

    def intercept_stream_unary(self, continuation, call_details, request_iterator):
        return continuation(self._with_token(call_details), request_iterator)

    def intercept_stream_stream(self, continuation, call_details, request_iterator):
        return continuation(self._with_token(call_details), request_iterator)


class _ClientCallDetails(grpc.ClientCallDetails):
    """grpc.ClientCallDetails is not always a namedtuple, so carry a copy."""

    def __init__(self, original, metadata):
        self.method = original.method
        self.timeout = original.timeout
        self.metadata = metadata
        self.credentials = original.credentials
        self.wait_for_ready = getattr(original, "wait_for_ready", None)
        self.compression = getattr(original, "compression", None)


def intercept(channel):
    """Wrap `channel` so token-gated calls carry the pairing token."""
    return grpc.intercept_channel(channel, AuthInterceptor(channel))
