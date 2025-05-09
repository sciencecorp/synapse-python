#!/usr/bin/env python3
import sys
import argparse
import binascii
import importlib
from typing import Type

from synapse.client.taps import Tap
from synapse.client.protobuf_helpers import parse_protobuf
from google.protobuf.message import Message


def load_message_type(message_type_path: str) -> Type[Message]:
    """Load a protobuf message type from its fully qualified path.

    Args:
        message_type_path (str): The fully qualified path to the message type (e.g. 'synapse.api.datatype_pb2.BroadbandFrame')

    Returns:
        Type[Message]: The message type class
    """
    parts = message_type_path.split(".")
    class_name = parts[-1]
    module_name = ".".join(parts[:-1])

    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"Could not load message type {message_type_path}: {e}")


def format_data(data):
    """Format raw bytes for display."""
    if isinstance(data, bytes) or isinstance(data, bytearray):
        # For binary data, show a hex summary
        if len(data) > 100:
            hex_data = binascii.hexlify(data[:50]).decode("ascii")
            return f"Binary data ({len(data)} bytes): {hex_data}... [truncated]"
        else:
            hex_data = binascii.hexlify(data).decode("ascii")
            return f"Binary data ({len(data)} bytes): {hex_data}"
    else:
        # For other types, use default string representation
        return str(data)


def main():
    parser = argparse.ArgumentParser(
        description="Example for using the Synapse Tap API"
    )
    parser.add_argument(
        "--uri", "-u", type=str, required=True, help="URI of the Synapse device"
    )
    parser.add_argument("--name", "-n", type=str, help="Name of the tap to connect to")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=5000,
        help="Timeout in milliseconds (default: 5000)",
    )
    parser.add_argument(
        "--count",
        "-c",
        type=int,
        default=None,
        help="Number of messages to receive (default: infinite)",
    )
    parser.add_argument(
        "--message-type",
        "-m",
        type=str,
        help="Fully qualified message type path (e.g. 'synapse.api.datatype_pb2.BroadbandFrame')",
    )
    args = parser.parse_args()

    # Create a tap client
    tap = Tap(args.uri, args.verbose)

    # List available taps
    print("Available taps:")
    taps = tap.list_taps()

    if not taps:
        print("No taps found")
        return 1

    for i, tap_info in enumerate(taps):
        print(
            f"  {i + 1}. {tap_info.name} - Type: {tap_info.message_type}, Endpoint: {tap_info.endpoint}"
        )

    # Determine which tap to connect to
    tap_name = args.name
    if not tap_name:
        # If name not provided, ask the user to select one
        try:
            selection = int(input("\nSelect a tap by number: "))
            if 1 <= selection <= len(taps):
                tap_name = taps[selection - 1].name
            else:
                print(f"Invalid selection: {selection}")
                return 1
        except ValueError:
            print("Invalid input. Please enter a number.")
            return 1

    # Load message type if provided
    message_type_class = None
    if args.message_type:
        try:
            message_type_class = load_message_type(args.message_type)
            print(f"Using message type: {message_type_class.__name__}")
        except ImportError as e:
            print(f"Warning: {e}")
            print("Will use raw data instead")

    # Connect to the selected tap
    print(f"\nConnecting to tap: {tap_name}")
    if not tap.connect(tap_name):
        print(f"Failed to connect to tap: {tap_name}")
        return 1

    print("Connected successfully!")

    try:
        if args.count:
            # Receive a specific number of messages
            print(f"\nReceiving {args.count} messages (timeout: {args.timeout}ms):")
            for i in range(args.count):
                raw_data = tap.read(args.timeout)
                if raw_data:
                    print(f"Message {i + 1}:")

                    # Parse data if message type was provided
                    if message_type_class:
                        parsed = parse_protobuf(raw_data, message_type_class)
                        if parsed:
                            print(f"Parsed message: {parsed}")
                        else:
                            print("Failed to parse as protobuf message")
                            print(f"Raw data: {format_data(raw_data)}")
                    else:
                        print(f"Raw data: {format_data(raw_data)}")

                    print()
                else:
                    print(f"Timeout waiting for message {i + 1}")
        else:
            # Stream messages until interrupted
            print("\nStreaming messages (Ctrl+C to stop):")
            count = 0
            for raw_data in tap.stream(args.timeout):
                count += 1
                print(f"Message {count}:")

                # Parse data if message type was provided
                if message_type_class:
                    parsed = parse_protobuf(raw_data, message_type_class)
                    if parsed:
                        print(f"Parsed message: {parsed}")
                    else:
                        print("Failed to parse as protobuf message")
                        print(f"Raw data: {format_data(raw_data)}")
                else:
                    print(f"Raw data: {format_data(raw_data)}")

                print()

    except KeyboardInterrupt:
        print("\nStream interrupted by user")

    finally:
        # Clean up
        print("\nDisconnecting...")
        tap.disconnect()
        print("Done")

    return 0


if __name__ == "__main__":
    sys.exit(main())
