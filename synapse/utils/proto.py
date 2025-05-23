import os
from pathlib import Path
from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.json_format import Parse
from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.api.app_pb2 import AppManifest
import synapse as syn


def load_client_protos(descriptor_file_paths, console):
    if not descriptor_file_paths:
        return

    pool = descriptor_pool.Default()
    for desc_path in descriptor_file_paths:
        if not os.path.exists(desc_path):
            console.print(f"[red]Warning:[/red] Descriptor file not found: {desc_path}")
            continue
        try:
            with open(desc_path, "rb") as f:
                descriptor_data = f.read()

            file_descriptor_set = descriptor_pb2.FileDescriptorSet()
            file_descriptor_set.ParseFromString(descriptor_data)

            for file_desc in file_descriptor_set.file:
                try:
                    pool.Add(file_desc)
                    console.print(
                        f"[green]Successfully loaded descriptor:[/green] {file_desc.name}"
                    )
                except Exception as e:
                    console.print(
                        f"[red]Warning:[/red] Could not add {file_desc.name} to pool: {e}"
                    )

        except Exception as e:
            console.print(f"[red]Error:[/red] Loading descriptor {desc_path}: {e}")


def load_config(path_to_config, console):
    # We support either a manifest or a device configuration.
    # First, try to load a device configuration
    try:
        json_text = open(path_to_config, "r").read()
        cfg_proto = Parse(json_text, DeviceConfiguration())
        return syn.Config.from_proto(cfg_proto)
    except Exception:
        pass

    # We couldn't load a device configuration, so try to load a manifest
    try:
        json_text = open(path_to_config, "r").read()
        manifest_proto = Parse(json_text, AppManifest())

        # First, load the descriptors from the proto_files (but look for .desc)
        manifest_dir = Path(path_to_config).resolve().parent

        desc_files = []
        for proto_file in manifest_proto.proto_files:
            # Convert .proto path to .desc path
            desc_file = Path(proto_file).with_suffix(".desc")
            desc_path = manifest_dir / desc_file
            desc_files.append(str(desc_path))

        if desc_files:
            load_client_protos(desc_files, console)

        # Now load the device configuration from the specified path
        device_config_path = manifest_dir / manifest_proto.device_config_path

        if device_config_path.exists():
            device_config_text = device_config_path.read_text()
            cfg_proto = Parse(device_config_text, DeviceConfiguration())
            return syn.Config.from_proto(cfg_proto)
        else:
            raise FileNotFoundError(f"Device config not found: {device_config_path}")

    except Exception:
        raise ValueError(
            f"Could not parse {path_to_config} as either device configuration or manifest"
        )

    return None
