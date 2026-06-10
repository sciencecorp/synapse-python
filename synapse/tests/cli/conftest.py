"""Workaround for pre-existing import bug in synapse.cli.

`synapse.cli.__init__` eagerly imports `synapse.cli.__main__`, which imports
`synapse.cli.settings`, which fails with
`ImportError: cannot import name 'SettingDescriptor' from 'synapse.api.device_pb2'`.

To let us import `synapse.cli.build` / `synapse.cli.peripherals` /
`synapse.cli.gateware` in unit tests, we pre-register stub modules for
`synapse.cli.settings` and `synapse.cli.__main__` in `sys.modules` BEFORE the
test collector first touches `synapse.cli`. pytest loads this conftest.py
before collecting any test in this directory.
"""

from __future__ import annotations

import sys
import types


def _install_cli_import_stubs() -> None:
    # Stub synapse.cli.settings so the real module's broken import is skipped.
    if "synapse.cli.settings" not in sys.modules:
        stub_settings = types.ModuleType("synapse.cli.settings")

        def _add_commands(_subparsers):  # pragma: no cover - never invoked in tests
            return None

        stub_settings.add_commands = _add_commands  # type: ignore[attr-defined]
        sys.modules["synapse.cli.settings"] = stub_settings

    # Stub synapse.cli.__main__ so synapse.cli's __init__ doesn't drag in the
    # whole CLI surface (which transitively imports settings the normal way).
    if "synapse.cli.__main__" not in sys.modules:
        stub_main = types.ModuleType("synapse.cli.__main__")

        def _main():  # pragma: no cover - never invoked in tests
            return None

        stub_main.main = _main  # type: ignore[attr-defined]
        sys.modules["synapse.cli.__main__"] = stub_main


_install_cli_import_stubs()


def fake_fpm_run(dist_dir: str, calls: list):
    """Return a ``subprocess.run`` stub that records argv and fakes fpm.

    When the recorded argv contains ``fpm`` (the real call runs fpm inside a
    docker image, so ``"fpm"`` is an element of the docker argv), drop a
    ``<name>_<version>_arm64.deb`` into *dist_dir* so the caller's post-fpm
    "did a .deb land?" verification passes. All other argv (docker clean,
    runtime extraction) are recorded and succeed as no-ops.
    """
    import os
    import subprocess as _subprocess

    def run(argv, *args, **kwargs):
        argv_list = list(argv) if isinstance(argv, (list, tuple)) else [argv]
        calls.append(argv_list)
        if "fpm" in argv_list:
            fpm_argv = argv_list[argv_list.index("fpm"):]
            name = fpm_argv[fpm_argv.index("-n") + 1]
            version = fpm_argv[fpm_argv.index("-v") + 1]
            os.makedirs(dist_dir, exist_ok=True)
            with open(
                os.path.join(dist_dir, f"{name}_{version}_arm64.deb"), "w"
            ) as fh:
                fh.write("fake-deb")
        return _subprocess.CompletedProcess(argv_list, 0, b"", b"")

    return run
