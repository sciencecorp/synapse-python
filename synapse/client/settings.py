from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING

from google.protobuf.struct_pb2 import Struct, Value

from synapse.api.device_pb2 import (
    DeviceSettings,
    SettingDescriptor,
    UpdateDeviceSettingsRequest,
)
from synapse.api.query_pb2 import QueryRequest

if TYPE_CHECKING:
    from synapse.client.device import Device


def get_all_settings(device: "Device") -> Dict[str, Any]:
    """
    Get all settings currently set on the device as a dict of {name: value}.

    Values are returned as native Python types (str/int/float/bool) based on
    each setting's Kind in the device's schema.
    """
    _, values, schema = _query_settings(device)
    kinds = {d.name: d.kind for d in schema}
    return {
        name: _value_to_python(v, kinds.get(name, SettingDescriptor.kKindUnknown))
        for name, v in values.fields.items()
    }


def get_setting(device: "Device", key: str) -> Any:
    """Get a single setting value by name."""
    _, values, schema = _query_settings(device)
    available = [d.name for d in schema]
    if key not in available and key not in values.fields:
        raise KeyError(f"Setting '{key}' not found. Available settings: {available}")

    if key not in values.fields:
        return None

    kind = next((d.kind for d in schema if d.name == key), SettingDescriptor.kKindUnknown)
    return _value_to_python(values.fields[key], kind)


def set_setting(device: "Device", key: str, value: Any) -> Any:
    """
    Set a single setting on the device. Returns the value the device reports
    after applying the update.
    """
    _, _, schema = _query_settings(device)
    descriptor = next((d for d in schema if d.name == key), None)
    if descriptor is None:
        available = [d.name for d in schema]
        raise KeyError(f"Setting '{key}' not found. Available settings: {available}")

    proto_value = _python_to_value(value, descriptor)

    update = DeviceSettings()
    update.values.fields[key].CopyFrom(proto_value)
    request = UpdateDeviceSettingsRequest(settings=update)

    response = device.update_device_settings(request)
    if not response or response.status.code != 0:
        error_msg = response.status.message if response else "Unknown error"
        raise RuntimeError(f"Failed to update settings on device: {error_msg}")

    updated_values = response.updated_settings.values
    if key in updated_values.fields:
        return _value_to_python(updated_values.fields[key], descriptor.kind)
    return None


def get_available_settings(device: "Device") -> Dict[str, str]:
    """
    Get all settings the device accepts and their kinds, as {name: kind_name}.

    Returns the device-declared schema, so the set of keys depends on which
    device is connected.
    """
    _, _, schema = _query_settings(device)
    return {d.name: SettingDescriptor.Kind.Name(d.kind) for d in schema}


# ---- helpers ----


def _query_settings(device: "Device"):
    """Run a kGetSettings query and return (response, values Struct, schema list)."""
    request = QueryRequest(
        query_type=QueryRequest.QueryType.kGetSettings, get_settings_query={}
    )
    response = device.query(request)
    if not response or response.status.code != 0:
        error_msg = response.status.message if response else "Unknown error"
        raise RuntimeError(f"Failed to get settings from device: {error_msg}")

    settings_response = response.get_settings_response
    return settings_response, settings_response.settings.values, list(settings_response.schema)


def _value_to_python(v: Value, kind: int) -> Any:
    which = v.WhichOneof("kind")
    if which == "string_value":
        return v.string_value
    if which == "number_value":
        # Int kinds round-trip as ints in Python even though Struct stores a double.
        if kind == SettingDescriptor.kInt:
            return int(v.number_value)
        return v.number_value
    if which == "bool_value":
        return v.bool_value
    if which == "null_value":
        return None
    return None


def _python_to_value(value: Any, descriptor: SettingDescriptor) -> Value:
    v = Value()
    kind = descriptor.kind

    if kind in (SettingDescriptor.kString, SettingDescriptor.kEnum):
        v.string_value = str(value)
    elif kind in (SettingDescriptor.kInt, SettingDescriptor.kDouble):
        try:
            v.number_value = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Invalid numeric value '{value}' for setting '{descriptor.name}': {e}"
            )
    elif kind == SettingDescriptor.kBool:
        if isinstance(value, bool):
            v.bool_value = value
        elif isinstance(value, str):
            v.bool_value = value.lower() in ("true", "1", "yes", "on")
        else:
            v.bool_value = bool(value)
    else:
        raise ValueError(
            f"Setting '{descriptor.name}' has unsupported kind "
            f"{SettingDescriptor.Kind.Name(kind)}"
        )

    if descriptor.allowed_values:
        if not any(_values_equal(v, allowed) for allowed in descriptor.allowed_values):
            allowed_py = [_value_to_python(a, kind) for a in descriptor.allowed_values]
            raise ValueError(
                f"Value '{value}' is not allowed for setting '{descriptor.name}'. "
                f"Allowed values: {allowed_py}"
            )

    return v


def _values_equal(a: Value, b: Value) -> bool:
    ak = a.WhichOneof("kind")
    bk = b.WhichOneof("kind")
    if ak != bk:
        return False
    if ak == "string_value":
        return a.string_value == b.string_value
    if ak == "number_value":
        return a.number_value == b.number_value
    if ak == "bool_value":
        return a.bool_value == b.bool_value
    return False
