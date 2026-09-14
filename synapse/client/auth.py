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
from pathlib import Path
from typing import Dict, Optional, Tuple

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

    # Create with 0600 from the outset rather than chmod-ing afterwards, so the
    # token is never briefly world-readable.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.writelines(lines)
    os.chmod(path, 0o600)
