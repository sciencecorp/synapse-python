from google.protobuf.json_format import Parse, ParseError
from synapse.api.device_pb2 import DeviceConfiguration
from synapse.api.app_pb2 import AppManifest
import synapse as syn


def load_device_config(path_to_json, console):
    # We support either a manifest or a device configuration.
    # First, try to load a device configuration
    try:
        with open(path_to_json, "r") as f:
            json_text = f.read()
    except FileNotFoundError:
        raise ValueError(f"File not found: {path_to_json}")
    except PermissionError:
        raise ValueError(f"Permission denied reading: {path_to_json}")
    except Exception as e:
        raise ValueError(f"Failed to read {path_to_json}: {e}")

    errors = []
    try:
        cfg_proto = Parse(json_text, DeviceConfiguration())
        return syn.Config.from_proto(cfg_proto)
    except ParseError as e:
        errors.append(f"DeviceConfiguration: {str(e)}")
    except Exception as e:
        errors.append(f"DeviceConfiguration: {type(e).__name__}: {str(e)}")

    # We couldn't load a device configuration, so try to load a manifest
    try:
        json_text = open(path_to_json, "r").read()
        manifest_proto = Parse(json_text, AppManifest())
        return syn.Config.from_proto(manifest_proto.device_config)
    except ParseError as e:
        errors.append(f"AppManifest: {str(e)}")
    except Exception:
        errors.append(f"AppManifest: {type(e).__name__}: {str(e)}")

    # Only reached here when we've failed to parse
    error_msg = f"Could not parse {path_to_json} as either format:\n"
    error_msg += "\n".join(f"  - {error}" for error in errors)
    raise ValueError(error_msg)
