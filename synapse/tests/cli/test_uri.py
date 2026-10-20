import importlib.util
from argparse import Namespace
from pathlib import Path

import synapse.cli

# conftest.py stubs synapse.cli.__main__, so load the real file under another name.
_spec = importlib.util.spec_from_file_location(
    "synapse_cli_main_for_test", Path(synapse.cli.__file__).with_name("__main__.py")
)
cli_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli_main)


def test_ip_with_port_skips_name_lookup(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("name lookup should not run")

    monkeypatch.setattr(cli_main, "find_device_by_name", fail)
    for uri in ["127.0.0.1", "127.0.0.1:50051", "::1"]:
        assert cli_main.setup_device_uri(Namespace(uri=uri)).uri == uri
