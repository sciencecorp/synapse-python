from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING
from google.protobuf.descriptor import FieldDescriptor

from synapse.api.device_pb2 import DeviceSettings, UpdateDeviceSettingsRequest
from synapse.api.query_pb2 import QueryRequest

if TYPE_CHECKING:
    from synapse.client.device import Device


def get_all_settings(device: "Device") -> Dict[str, Any]:
    """
    Get all non-default settings from device as a dictionary.

    Args:
        device: Device instance to fetch settings from

    Returns:
        Dictionary of setting names to values

    Raises:
        RuntimeError: If failed to fetch settings from device
    """
    request = QueryRequest(
        query_type=QueryRequest.QueryType.kGetSettings, get_settings_query={}
    )
    response = device.query(request)

    if not response or response.status.code != 0:
        error_msg = response.status.message if response else "Unknown error"
        raise RuntimeError(f"Failed to get settings from device: {error_msg}")

    settings_proto = response.get_settings_response.settings
    settings_dict = {}

    for field in settings_proto.DESCRIPTOR.fields:
        field_name = field.name
        field_value = getattr(settings_proto, field_name)

        # Check if field has non-default value
        if _has_non_default_value(settings_proto, field, field_value):
            settings_dict[field_name] = field_value

    return settings_dict


def get_setting(device: "Device", key: str) -> Any:
    """
    Get a specific setting value from device.

    Args:
        device: Device instance
        key: Setting name

    Returns:
        Setting value

    Raises:
        RuntimeError: If failed to fetch settings
        KeyError: If setting doesn't exist
    """
    request = QueryRequest(
        query_type=QueryRequest.QueryType.kGetSettings, get_settings_query={}
    )
    response = device.query(request)

    if not response or response.status.code != 0:
        error_msg = response.status.message if response else "Unknown error"
        raise RuntimeError(f"Failed to get settings from device: {error_msg}")

    settings_proto = response.get_settings_response.settings

    if not _has_field(settings_proto, key):
        available_fields = [field.name for field in settings_proto.DESCRIPTOR.fields]
        raise KeyError(
            f"Setting '{key}' not found. Available settings: {available_fields}"
        )

    return getattr(settings_proto, key)


def set_setting(device: "Device", key: str, value: Any) -> Any:
    """
    Set a specific setting value on device.

    Args:
        device: Device instance
        key: Setting name
        value: Setting value

    Returns:
        The actual value that was set (after any device processing)

    Raises:
        RuntimeError: If failed to update settings
        KeyError: If setting doesn't exist
        ValueError: If value is invalid for the setting type
    """
    # Create a new settings proto with just this field set
    settings_proto = DeviceSettings()

    field_descriptor = _get_field_descriptor(settings_proto, key)
    if not field_descriptor:
        available_fields = [field.name for field in settings_proto.DESCRIPTOR.fields]
        raise KeyError(
            f"Setting '{key}' not found. Available settings: {available_fields}"
        )

    # Convert and validate value based on field type
    converted_value = _convert_and_validate_value(field_descriptor, value)
    setattr(settings_proto, key, converted_value)

    # Send to device
    request = UpdateDeviceSettingsRequest(settings=settings_proto)
    response = device.update_device_settings(request)

    if not response or response.status.code != 0:
        error_msg = response.status.message if response else "Unknown error"
        raise RuntimeError(f"Failed to update settings on device: {error_msg}")

    # Return the actual value that was set
    return getattr(response.updated_settings, key)


def get_available_settings() -> Dict[str, str]:
    """
    Get all available setting names and their types.

    Returns:
        Dictionary mapping setting names to their protobuf type names
    """
    settings_proto = DeviceSettings()
    return {
        field.name: _get_field_type_name(field)
        for field in settings_proto.DESCRIPTOR.fields
    }


# Helper functions
def _has_field(settings_proto: DeviceSettings, field_name: str) -> bool:
    """Check if a field exists in the protobuf."""
    return any(field.name == field_name for field in settings_proto.DESCRIPTOR.fields)


def _get_field_descriptor(
    settings_proto: DeviceSettings, field_name: str
) -> FieldDescriptor:
    """Get field descriptor by name."""
    for field in settings_proto.DESCRIPTOR.fields:
        if field.name == field_name:
            return field
    return None


def _has_non_default_value(
    settings_proto: DeviceSettings, field: FieldDescriptor, value: Any
) -> bool:
    """Check if a field has a non-default value."""
    # For message fields, use HasField to check presence
    if field.type == field.TYPE_MESSAGE:
        return settings_proto.HasField(field.name)

    # For scalar fields, check if value is not default
    if field.type == field.TYPE_STRING:
        return value != ""
    elif field.type in [
        field.TYPE_INT32,
        field.TYPE_UINT32,
        field.TYPE_INT64,
        field.TYPE_UINT64,
    ]:
        return value != 0
    elif field.type in [field.TYPE_FLOAT, field.TYPE_DOUBLE]:
        return value != 0.0
    elif field.type == field.TYPE_BOOL:
        return value is True
    else:
        # For other types, always display
        return True


def _convert_and_validate_value(field: FieldDescriptor, value: Any) -> Any:
    """Convert and validate a value for a specific field type."""
    try:
        if field.type == field.TYPE_STRING:
            return str(value)
        elif field.type in [field.TYPE_INT32, field.TYPE_UINT32]:
            return int(value)
        elif field.type in [field.TYPE_INT64, field.TYPE_UINT64]:
            return int(value)
        elif field.type in [field.TYPE_FLOAT, field.TYPE_DOUBLE]:
            return float(value)
        elif field.type == field.TYPE_BOOL:
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            else:
                return bool(value)
        else:
            # For other types, try direct assignment
            return value
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid value '{value}' for field '{field.name}' of type {_get_field_type_name(field)}: {e}"
        )


def _get_field_type_name(field: FieldDescriptor) -> str:
    """Get human-readable field type name."""
    type_names = {
        field.TYPE_STRING: "string",
        field.TYPE_INT32: "int32",
        field.TYPE_UINT32: "uint32",
        field.TYPE_INT64: "int64",
        field.TYPE_UINT64: "uint64",
        field.TYPE_FLOAT: "float",
        field.TYPE_DOUBLE: "double",
        field.TYPE_BOOL: "bool",
        field.TYPE_MESSAGE: "message",
    }
    return type_names.get(field.type, f"unknown({field.type})")
