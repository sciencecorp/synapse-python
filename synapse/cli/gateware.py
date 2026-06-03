"""Gateware build helpers for the ``synapsectl peripherals`` CLI.

This module exposes the LM_LICENSE_FILE helper used by the gateware docker
invocation, the :func:`run_gateware_build` runner that wraps
``axon-peripheral-sdk build`` inside the gateware container, and the
:func:`_gateware_passthrough` dispatcher used by
``synapsectl peripherals gateware <verb> [args...]``.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Mapping, Sequence

from rich.console import Console

console = Console()


_NON_POSIX_MSG = (
    "synapsectl peripherals gateware requires a POSIX host (Linux or macOS): "
    "os.getuid() / os.getgid() are needed to set the container's --user flag "
    "so files written under the bind-mount belong to you. On Windows, invoke "
    "axon-peripheral-sdk directly inside WSL or a Linux container."
)


# Module-level constant for floating-license detection. Matches both
# single-server (``port@host``) and colon-joined multi-server FlexLM
# redundancy strings (``port1@host1:port2@host2``). Rejects anything
# containing ``/`` so file paths fall through to the path branch even
# when they contain ``@`` (e.g. ``/home/user@work/license.dat``).
# ``\Z`` (not ``$``) anchors the end strictly — ``$`` would match before a
# trailing newline and let pathological values like ``"27000@host\n"`` slip
# through into the container as an LM_LICENSE_FILE env var.
_PORT_AT_HOST_RE = re.compile(r"\A[^/\s]+@[^/\s]+\Z")

_LICENSE_UNSET_MSG = (
    "LM_LICENSE_FILE is not set. Set it to a license file path "
    "(e.g. /etc/lattice/license.dat) or a port@host floating-license "
    "spec (e.g. 7788@licenseserver)."
)

_CONTAINER_LICENSE_PATH = "/opt/lattice/license.dat"


class LicenseUnsetError(RuntimeError):
    """Raised when ``LM_LICENSE_FILE`` is unset or empty."""


def _host_mac_address() -> str | None:
    """Return the host's primary MAC as ``xx:xx:xx:xx:xx:xx``, or ``None``.

    Lattice node-locked licenses are bound to the host's MAC. When we run
    Radiant inside a container, FlexLM sees the container's virtual eth0
    MAC (auto-generated, different from the host) and rejects the license.
    Passing ``--mac-address`` to ``docker run`` forces the container's eth0
    onto the host's MAC so the license validates.

    Uses :func:`uuid.getnode`, which falls back to a random multicast MAC
    when no real hardware address is available; we detect that case via
    the multicast bit and return ``None`` so the caller can skip the
    ``--mac-address`` flag rather than passing a useless random value.
    """
    node = uuid.getnode()
    if (node >> 40) & 0x01:
        return None
    return ":".join(f"{(node >> (8 * i)) & 0xFF:02x}" for i in range(5, -1, -1))


def build_license_docker_args(
    env: Mapping[str, str] = os.environ,
) -> list[str]:
    """Return the ``docker run`` flags that forward the Radiant license.

    Three modes:

    - **File path** (default branch): resolved with
      ``Path(value).expanduser().resolve(strict=True)`` and bind-mounted
      read-only into the container at ``/opt/lattice/license.dat``. The
      host's MAC is also forwarded via ``--mac-address`` (when detectable)
      so the container's eth0 matches the node-locked license's HOSTID.
    - **Floating** (``port@host`` or ``port1@host1:port2@host2``): the
      value is forwarded verbatim via ``-e LM_LICENSE_FILE=<value>``
      with no bind-mount or MAC override — a license server checks out
      tokens by network, hostid is irrelevant.
    - **Unset / empty**: raises :class:`LicenseUnsetError`.

    The helper reads only from ``env`` and never falls back to
    ``os.environ`` when the key is missing from the supplied mapping.
    """
    value = env.get("LM_LICENSE_FILE", "")
    if not value:
        raise LicenseUnsetError(_LICENSE_UNSET_MSG)

    if _PORT_AT_HOST_RE.match(value):
        return ["-e", f"LM_LICENSE_FILE={value}"]

    resolved = Path(value).expanduser().resolve(strict=True)
    args = [
        "-v",
        f"{resolved}:{_CONTAINER_LICENSE_PATH}:ro",
        "-e",
        f"LM_LICENSE_FILE={_CONTAINER_LICENSE_PATH}",
    ]
    mac = _host_mac_address()
    if mac is not None:
        args.extend(["--mac-address", mac])
    return args


_SDK_BUILD_CMD = "axon-peripheral-sdk build --project src/gateware"


def run_gateware_build(
    peripheral_dir: str,
    image_tag: str,
    env: Mapping[str, str] = os.environ,
) -> str:
    """Invoke ``axon-peripheral-sdk build`` inside the gateware container.

    Returns the absolute path to the newest ``sdk_*.bit`` emitted under
    ``<peripheral_dir>/src/gateware/build/bitstreams/``.

    Raises:
      LicenseUnsetError: if ``LM_LICENSE_FILE`` is unset (propagated from
        :func:`build_license_docker_args`).
      subprocess.CalledProcessError: if the container's build exits non-zero.
      FileNotFoundError: if the build succeeds but no bitstream is emitted.
    """
    license_args = build_license_docker_args(env)

    abs_peripheral_dir = os.path.abspath(peripheral_dir)
    argv = [
        "docker",
        "run",
        "--rm",
        "--user",
        "dev",
        "-v",
        f"{abs_peripheral_dir}:/home/workspace",
        "-w",
        "/home/workspace",
        *license_args,
        image_tag,
        "/bin/bash",
        "-lc",
        _SDK_BUILD_CMD,
    ]
    subprocess.run(argv, check=True)

    bit_glob = os.path.join(
        abs_peripheral_dir, "src", "gateware", "build", "bitstreams", "sdk_*.bit"
    )
    matches = glob.glob(bit_glob)
    if not matches:
        raise FileNotFoundError(
            "axon-peripheral-sdk build completed but no sdk_*.bit was emitted "
            "under src/gateware/build/bitstreams/"
        )

    matches.sort(key=os.path.getmtime, reverse=True)
    chosen = matches[0]
    if len(matches) > 1:
        console.print(
            f"[yellow]Multiple bitstreams matched; selected newest: {chosen}[/yellow]"
        )
    return chosen


def _gateware_passthrough(
    argv: Sequence[str],
    peripheral_dir: str,
    license_args: Sequence[str],
    gateware_image_tag: str,
) -> int:
    """Forward ``argv`` verbatim to ``axon-peripheral-sdk`` inside the container.

    Builds the docker-run command in argv-list form (``shell=False``) so the
    SDK sees its arguments byte-for-byte — no shell concatenation, no
    ``shlex.quote`` escaping. Returns the SDK's exit code; the caller is
    responsible for translating it into a ``sys.exit``.

    POSIX-only: ``os.getuid()`` / ``os.getgid()`` are required to construct the
    ``--user`` argument. On a non-POSIX host (Python-on-Windows) those
    attributes are missing and we exit with a clear error rather than silently
    falling back to a hard-coded UID — Docker-for-Windows bind-mount UID
    semantics are messy enough that a wrong default would cause confusing
    file-ownership bugs.
    """
    try:
        host_uid = os.getuid()
        host_gid = os.getgid()
    except AttributeError:
        sys.exit(_NON_POSIX_MSG)

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(peripheral_dir)}:/home/workspace",
        "-w",
        "/home/workspace",
        "--user",
        f"{host_uid}:{host_gid}",
        # Tell the SDK which frontend launched it so its user-facing "next
        # steps" hints and --help examples name `synapsectl peripherals
        # gateware <verb>` (what the user actually typed) rather than the
        # `axon-peripheral-sdk <verb>` binary we forward to inside the container.
        "-e",
        "AXON_PERIPHERAL_SDK_FRONTEND=synapsectl peripherals gateware",
        *license_args,
        gateware_image_tag,
        "axon-peripheral-sdk",
        *argv,
    ]
    # check=False: surface the SDK's exit code rather than raising on non-zero.
    result = subprocess.run(cmd, check=False)
    return result.returncode
