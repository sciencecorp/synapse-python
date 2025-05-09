from typing import Optional, Type, TypeVar
from google.protobuf.message import Message

# Generic type for protobuf messages
T = TypeVar("T", bound=Message)


def parse_protobuf(data: bytes, message_type: Type[T]) -> Optional[T]:
    """Parse raw bytes into a protobuf message of the specified type.

    Args:
        data (bytes): Raw binary data.
        message_type (Type[T]): The protobuf message class to use for parsing.

    Returns:
        Optional[T]: The parsed protobuf message, or None if parsing failed.
    """
    if not data:
        return None

    try:
        message = message_type()
        message.ParseFromString(data)
        return message
    except Exception:
        return None
