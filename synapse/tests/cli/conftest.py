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
