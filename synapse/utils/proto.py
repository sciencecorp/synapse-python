from google.protobuf.json_format import Parse
from synapse.api.device_pb2 import DeviceConfiguration
from synapse.api.app_pb2 import AppManifest
import synapse as syn


def load_device_config(path_to_json, console):
    # We support either a manifest or a device configuration.
    # First, try to load a device configuration
    try:
        json_text = open(path_to_json, "r").read()
        cfg_proto = Parse(json_text, DeviceConfiguration())
        return syn.Config.from_proto(cfg_proto)
    except Exception:
        pass

    # We couldn't load a device configuration, so try to load a manifest
    try:
        json_text = open(path_to_json, "r").read()
        manifest_proto = Parse(json_text, AppManifest())
        return syn.Config.from_proto(manifest_proto.device_config)
    except Exception:
        raise ValueError(
            f"Could not parse {path_to_json} as either device configuration or manifest"
        )

    return None
