from synapse.client.taps import Tap
from synapse.api.logging_pb2 import LogEntry
from synapse.utils.log import log_entry_to_str

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.text import Text

import time


class TapHealthMonitor:
    """Health monitor for streaming tap data with real-time statistics display."""

    def __init__(self, console: Console):
        self.console = console
        self.message_count = 0
        self.total_bytes = 0
        self.start_time = None
        self.last_log_entry = None  # Store the last decoded log entry

    def start(self):
        """Start the monitoring session."""
        self.start_time = time.time()
        self.message_count = 0
        self.total_bytes = 0
        self.last_log_entry = None

    def update(self, message_size: int, message_data: bytes = None) -> Text:
        """Update statistics with a new message and return formatted display text."""
        current_time = time.time()
        self.message_count += 1
        self.total_bytes += message_size

        # Try to decode as LogEntry if message_data is provided
        if message_data:
            try:
                log_entry = LogEntry()
                log_entry.ParseFromString(message_data)
                self.last_log_entry = log_entry
            except Exception:
                # Not a LogEntry or failed to parse, ignore
                pass

        # Calculate stats
        elapsed_time = current_time - self.start_time
        msgs_per_sec = self.message_count / elapsed_time if elapsed_time > 0 else 0
        bandwidth_bps = self.total_bytes / elapsed_time if elapsed_time > 0 else 0

        # Format bandwidth
        bandwidth_str = self._format_bandwidth(bandwidth_bps)

        # Create formatted display text
        return self._create_display_text(
            self.message_count, msgs_per_sec, bandwidth_str, message_size
        )

    def _format_bandwidth(self, bandwidth_bps: float) -> str:
        """Format bandwidth with appropriate units."""
        if bandwidth_bps >= 1024 * 1024:
            return f"{bandwidth_bps / (1024 * 1024):.2f} MB/s"
        elif bandwidth_bps >= 1024:
            return f"{bandwidth_bps / 1024:.2f} KB/s"
        else:
            return f"{bandwidth_bps:.1f} B/s"

    def _create_display_text(
        self, msg_count: int, rate: float, bandwidth: str, latest_size: int
    ) -> Text:
        """Create styled text for the live display."""
        stats_text = Text()
        stats_text.append("Messages: ", style="bold")
        stats_text.append(f"{msg_count:,}", style="cyan")
        stats_text.append(" | msgs/sec: ", style="bold")
        stats_text.append(f"{rate:.1f}/s", style="green")
        stats_text.append(" | Bandwidth: ", style="bold")
        stats_text.append(bandwidth, style="yellow")
        stats_text.append(" | Latest: ", style="bold")
        stats_text.append(f"{latest_size:,} bytes", style="magenta")
        stats_text.append(" | Runtime: ", style="bold")
        stats_text.append(f"{time.time() - self.start_time:.1f}s", style="blue")

        # Add log entry information if available
        if self.last_log_entry:
            stats_text.append("\n")
            stats_text.append("Last Log: ", style="bold")
            log_str = log_entry_to_str(self.last_log_entry)
            stats_text.append(log_str, style="white")

        return stats_text


def add_commands(subparsers):
    tap_parser = subparsers.add_parser("taps", help="Interact with taps on the network")

    tap_subparsers = tap_parser.add_subparsers(title="Tap Commands")

    # Now add the list parser to the tap_subparsers
    list_parser = tap_subparsers.add_parser("list", help="list the taps for a device")
    list_parser.set_defaults(func=list_taps)

    stream_parser = tap_subparsers.add_parser("stream", help="Stream a tap")
    stream_parser.add_argument("tap_name", type=str)
    stream_parser.set_defaults(func=stream_taps)


def list_taps(args):
    tap = Tap(args.uri, args.verbose)

    console = Console()

    taps = tap.list_taps()
    table = Table(title="Available Taps", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Message Type", style="green")
    table.add_column("Endpoint", style="green")

    for tap in taps:
        table.add_row(tap.name, tap.message_type, tap.endpoint)

    console.print(table)


def stream_taps(args):
    tap = Tap(args.uri, args.verbose)
    taps = tap.list_taps()

    if args.tap_name not in [tap.name for tap in taps]:
        print(f"Tap {args.tap_name} not found")
        return

    # Get the selected tap info to check message type
    selected_tap = None
    for t in taps:
        if t.name == args.tap_name:
            selected_tap = t
            break

    tap.connect(args.tap_name)

    console = Console()
    console.print(f"[bold cyan]Streaming tap:[/] [green]{args.tap_name}[/]")

    # Show message type info if available
    if selected_tap and selected_tap.message_type:
        console.print(f"[dim]Message type: {selected_tap.message_type}[/]")
        if selected_tap.message_type == "synapse.LogEntry":
            console.print("[dim]Log messages will be decoded and displayed[/]")

    console.print("[dim]Press Ctrl+C to stop[/]\n")

    # Initialize health monitor
    monitor = TapHealthMonitor(console)
    monitor.start()

    # Create initial display
    initial_text = Text("Waiting for messages...", style="dim")

    try:
        with Live(initial_text, console=console, refresh_per_second=10) as live:
            for message in tap.stream():
                message_size = len(message)

                # Update statistics and get formatted display
                # Pass message data if this might be a LogEntry tap
                message_data = None
                if selected_tap and selected_tap.message_type == "synapse.LogEntry":
                    message_data = message

                stats_text = monitor.update(message_size, message_data)

                # Update the live display
                live.update(stats_text)
    except KeyboardInterrupt:
        pass
    finally:
        tap.disconnect()
