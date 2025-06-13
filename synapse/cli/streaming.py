import os
import queue
import threading
import time
import h5py
from datetime import datetime
from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich.text import Text

import synapse as syn
from synapse.api.status_pb2 import DeviceState, StatusCode
from synapse.client.taps import Tap
from synapse.utils.proto import load_device_config
from synapse.api.datatype_pb2 import BroadbandFrame


class StreamMonitor:
    def __init__(self, console: Console):
        self.console = console
        self.start_time = time.time()
        self.message_count = 0
        self.last_update = time.time()
        self.last_count = 0
        self.last_sequence = 0
        self.total_dropped = 0
        self.queue = queue.Queue(maxsize=100)
        self.stop_event = threading.Event()
        self.monitor_thread = None

    def start(self):
        """Start monitoring in separate thread"""
        self.start_time = time.time()
        self.last_update = self.start_time
        self.message_count = 0
        self.last_count = 0
        self.last_sequence = 0
        self.total_dropped = 0
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.start()

    def stop(self):
        """Stop monitoring thread"""
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join()

    def put(self, frame: BroadbandFrame):
        """Add frame to monitoring queue (non-blocking)"""
        try:
            self.queue.put(frame, block=False)
        except queue.Full:
            # Drop frame if queue is full to prevent blocking
            pass

    def _monitor_loop(self):
        """Process frames for monitoring in separate thread"""
        while not self.stop_event.is_set():
            try:
                frame = self.queue.get(timeout=0.1)
                self._update_stats(frame)
            except queue.Empty:
                continue

    def _update_stats(self, frame: BroadbandFrame):
        """Update statistics from frame"""
        self.message_count += 1

        # Check for dropped packets
        if self.last_sequence != 0:
            expected_sequence = self.last_sequence + 1
            if frame.sequence_number != expected_sequence:
                self.total_dropped += frame.sequence_number - expected_sequence
        self.last_sequence = frame.sequence_number

    def get_current_stats(self) -> Text:
        """Get current statistics as formatted text"""
        current_time = time.time()

        # Calculate message rate
        elapsed = current_time - self.last_update
        if elapsed >= 1.0:  # Update rate every second
            rate = (self.message_count - self.last_count) / elapsed
            self.last_count = self.message_count
            self.last_update = current_time
        else:
            rate = (
                (self.message_count - self.last_count)
                / (current_time - self.last_update)
                if elapsed > 0
                else 0
            )

        # Calculate packet loss percentage
        total_expected = self.message_count + self.total_dropped
        loss_percent = (
            (self.total_dropped / total_expected * 100) if total_expected > 0 else 0
        )

        # Create styled text
        stats_text = Text()
        stats_text.append("Messages: ", style="bold")
        stats_text.append(f"{self.message_count:,}", style="cyan")
        stats_text.append(" | msgs/sec: ", style="bold")
        stats_text.append(f"{rate:.1f}/s", style="green")
        stats_text.append(" | Dropped: ", style="bold")
        stats_text.append(f"{self.total_dropped:,}", style="red")
        stats_text.append(" | Loss: ", style="bold")
        stats_text.append(f"{loss_percent:.2f}%", style="yellow")
        stats_text.append(" | Runtime: ", style="bold")
        stats_text.append(f"{current_time - self.start_time:.1f}s", style="blue")

        return stats_text


class BroadbandFrameWriter:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.data_queue = queue.Queue(maxsize=2000)  # Increased queue size
        self.stop_event = threading.Event()
        self.writer_thread = None

        # Stats tracking
        self.start_time = time.time()
        self.frames_received = 0
        self.samples_received = 0
        self.last_sequence = 0
        self.dropped_frames = 0

        # Create HDF5 file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(output_dir, f"broadband_data_{timestamp}.h5")
        self.file = h5py.File(self.filename, "w")

        # Create datasets
        self.timestamp_dataset = self.file.create_dataset(
            "/acquisition/timestamp", shape=(0,), maxshape=(None,), dtype="uint64"
        )
        self.sequence_dataset = self.file.create_dataset(
            "/acquisition/sequence_number", shape=(0,), maxshape=(None,), dtype="uint64"
        )
        # Create frame data dataset as a flat array of samples
        self.frame_data_dataset = self.file.create_dataset(
            "/acquisition/ElectricalSeries", shape=(0,), maxshape=(None,), dtype="int32"
        )

        # Buffer for collecting frames before writing
        self.frame_buffer = []
        self.buffer_size = 500  # Reduced buffer size for more frequent writes

    def get_stats(self):
        """Get current statistics"""
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return {
                "frames_per_sec": 0,
                "samples_per_sec": 0,
                "total_frames": 0,
                "total_samples": 0,
                "dropped_frames": 0,
                "last_sequence": 0,
            }

        return {
            "frames_per_sec": self.frames_received / elapsed,
            "samples_per_sec": self.samples_received / elapsed,
            "total_frames": self.frames_received,
            "total_samples": self.samples_received,
            "dropped_frames": self.dropped_frames,
            "last_sequence": self.last_sequence,
        }

    def set_attributes(
        self, sample_rate_hz: float, channels: list, session_description: str = ""
    ):
        """Set HDF5 attributes similar to C++ implementation"""
        # Set basic attributes
        self.file.attrs["sample_rate_hz"] = sample_rate_hz
        if session_description:
            self.file.attrs["session_description"] = session_description

        # Set session start time
        self.file.attrs["session_start_time"] = datetime.now().isoformat()

        # Set device type
        device_group = self.file.create_group("general/device")
        device_group.attrs["device_type"] = "SciFi"

        # Create electrodes group and write channel IDs
        electrodes_group = self.file.create_group(
            "general/extracellular_ephys/electrodes"
        )
        channel_ids = channels
        electrodes_group.create_dataset("id", data=channel_ids, dtype="uint32")

    def start(self):
        """Start the writer thread"""
        self.writer_thread = threading.Thread(target=self._write_loop)
        self.writer_thread.start()

    def stop(self):
        """Stop the writer thread and wait for it to finish"""
        self.stop_event.set()
        if self.writer_thread:
            self.writer_thread.join()
        self.flush()
        self.file.close()

    def put(self, frame: BroadbandFrame):
        """Add frame to the write queue (non-blocking)"""
        # Update stats
        self.frames_received += 1
        self.samples_received += len(frame.frame_data)

        # Check for dropped frames
        if self.last_sequence != 0:
            expected_sequence = self.last_sequence + 1
            if frame.sequence_number != expected_sequence:
                self.dropped_frames += frame.sequence_number - expected_sequence
        self.last_sequence = frame.sequence_number

        try:
            self.data_queue.put(frame, block=False)
        except queue.Full:
            # If queue is full, we'll drop the oldest data
            try:
                self.data_queue.get_nowait()
                self.data_queue.put(frame, block=False)
            except queue.Empty:
                pass

    def put_batch(self, frames: list):
        """Add multiple frames to the write queue efficiently"""
        for frame in frames:
            self.frames_received += 1
            self.samples_received += len(frame.frame_data)

            # Check for dropped frames
            if self.last_sequence != 0:
                expected_sequence = self.last_sequence + 1
                if frame.sequence_number != expected_sequence:
                    self.dropped_frames += frame.sequence_number - expected_sequence
            self.last_sequence = frame.sequence_number

        # Try to add all frames to queue
        for frame in frames:
            try:
                self.data_queue.put(frame, block=False)
            except queue.Full:
                # If queue is full, drop oldest and try again
                try:
                    self.data_queue.get_nowait()
                    self.data_queue.put(frame, block=False)
                except queue.Empty:
                    pass

    def _write_loop(self):
        """Main writing loop that consumes data from the queue"""
        while not self.stop_event.is_set() or not self.data_queue.empty():
            try:
                frame = self.data_queue.get(timeout=0.1)
                self.frame_buffer.append(frame)

                # Write when buffer is full
                if len(self.frame_buffer) >= self.buffer_size:
                    self._write_buffer()

            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error writing data: {e}")
                continue

    def _write_buffer(self):
        """Write the buffered frames to disk"""
        if not self.frame_buffer:
            return

        # Get current sizes
        current_timestamp_size = self.timestamp_dataset.shape[0]
        current_frame_size = self.frame_data_dataset.shape[0]
        num_frames = len(self.frame_buffer)

        # Resize datasets
        new_timestamp_size = current_timestamp_size + num_frames
        new_frame_size = current_frame_size + (
            num_frames * len(self.frame_buffer[0].frame_data)
        )

        self.timestamp_dataset.resize(new_timestamp_size, axis=0)
        self.sequence_dataset.resize(new_timestamp_size, axis=0)
        self.frame_data_dataset.resize(new_frame_size, axis=0)

        # Write data
        for i, frame in enumerate(self.frame_buffer):
            idx = current_timestamp_size + i
            self.timestamp_dataset[idx] = frame.timestamp_ns
            self.sequence_dataset[idx] = frame.sequence_number

            # Write frame data
            frame_start = current_frame_size + (i * len(frame.frame_data))
            frame_end = frame_start + len(frame.frame_data)
            self.frame_data_dataset[frame_start:frame_end] = frame.frame_data

        # Clear buffer
        self.frame_buffer = []

        # Flush to disk
        self.flush()

    def flush(self):
        """Flush all datasets to disk"""
        if self.frame_buffer:
            self._write_buffer()
        self.timestamp_dataset.flush()
        self.sequence_dataset.flush()
        self.frame_data_dataset.flush()
        self.file.flush()


def create_status_table(writer: BroadbandFrameWriter) -> Table:
    """Create a status table for display"""
    stats = writer.get_stats()
    table = Table(title="Streaming Status")

    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Frames/sec", f"{stats['frames_per_sec']:.1f}")
    table.add_row("Samples/sec", f"{stats['samples_per_sec']:.1f}")
    table.add_row("Total Frames", str(stats["total_frames"]))
    table.add_row("Total Samples", str(stats["total_samples"]))
    table.add_row("Dropped Frames", str(stats["dropped_frames"]))
    table.add_row("Last Sequence", str(stats["last_sequence"]))

    return table


def add_commands(subparsers):
    read_parser = subparsers.add_parser(
        "read", help="Read from a device's Broadband Tap"
    )

    read_parser.add_argument(
        "config", type=str, help="Device configuration or manifest file"
    )

    # Output options, we will save as HDF5
    read_parser.add_argument("--output", type=str, help="Output directory")
    read_parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing files"
    )
    read_parser.add_argument(
        "--plot", action="store_true", help="Show real-time plot of Broadband Data"
    )
    read_parser.add_argument(
        "--tap-name",
        type=str,
        help="Specific tap name to connect to (if not specified, will auto-select first BroadbandFrame tap)",
    )
    read_parser.add_argument(
        "--list-taps", action="store_true", help="List all available taps and exit"
    )

    read_parser.set_defaults(func=read)


def configure_device(device, config, console):
    with console.status("Configuring device...", spinner="bouncingBall"):
        # check if we are running
        info = device.info()
        if info.status.state == DeviceState.kRunning:
            console.log(
                "[bold yellow]Device is already running, reading from existing tap[/bold yellow]"
            )
            return True

        # Apply the configuration to the device
        configure_status = device.configure_with_status(config)
        if configure_status.code != StatusCode.kOk:
            console.print(
                f"[bold red]Failed to configure device: {configure_status.message}[/bold red]"
            )
            return False
        console.log("[green]Configured device[/green]")

    return True


def start_device(device, console):
    info = device.info()
    if info.status.state == DeviceState.kRunning:
        return True

    with console.status("Starting device...", spinner="bouncingBall"):
        start_status = device.start_with_status()
        if start_status.code != StatusCode.kOk:
            console.print(
                f"[bold red]Failed to start device: {start_status.message}[/bold red]"
            )
            return False
    return True


def setup_output(args, console):
    if not args.output:
        console.print("[bold red]No output directory specified[/bold red]")
        return False

    # Create the output directory if it doesn't exist
    os.makedirs(args.output, exist_ok=True)
    return True


def list_available_taps(args, device, console):
    """List all available taps on the device"""
    read_tap = Tap(args.uri, args.verbose)
    taps = read_tap.list_taps()

    if not taps:
        console.print("[bold red]No taps found on device[/bold red]")
        return

    console.print("\n[bold cyan]Available Taps:[/bold cyan]")
    console.print("=" * 50)

    supported_count = 0
    for tap in taps:
        is_supported = tap.message_type == "synapse.BroadbandFrame"
        if is_supported:
            supported_count += 1
            console.print(
                f"[green]Name:[/green] {tap.name} [bold green]✓ SUPPORTED[/bold green]"
            )
        else:
            console.print(f"[green]Name:[/green] {tap.name}")

        console.print(f"[blue]Type:[/blue] {tap.message_type}")
        console.print(f"[yellow]Endpoint:[/yellow] {tap.endpoint}")

        if not is_supported:
            console.print(
                "[dim red]Note: Only synapse.BroadbandFrame taps are supported[/dim red]"
            )
        console.print("-" * 30)

    console.print(
        f"\n[bold]Total: {len(taps)} taps found, {supported_count} supported[/bold]"
    )


def detect_stream_parameters(broadband_tap, console):
    """Detect sample rate and available channels from the first message"""
    console.log("[cyan]Detecting stream parameters from first message...[/cyan]")

    try:
        # Get the first message to detect parameters
        first_message = broadband_tap.read(timeout_ms=5000)  # 5 second timeout
        if not first_message:
            console.print(
                "[bold red]Failed to receive first message for parameter detection[/bold red]"
            )
            return None, None, None

        # Parse the first frame
        first_frame = BroadbandFrame()
        first_frame.ParseFromString(first_message)

        # Extract parameters
        sample_rate = first_frame.sample_rate_hz
        num_channels = len(first_frame.frame_data)
        available_channels = list(range(num_channels))

        console.log(f"[green]Detected sample rate: {sample_rate} Hz[/green]")
        console.log(
            f"[green]Detected {num_channels} channels (0-{num_channels - 1})[/green]"
        )

        return sample_rate, available_channels, first_frame

    except Exception as e:
        console.print(f"[bold red]Error detecting stream parameters: {e}[/bold red]")
        return None, None, None


def get_broadband_tap(args, device, console):
    read_tap = Tap(args.uri, args.verbose)
    taps = read_tap.list_taps()

    # If user specified a tap name, try to use it first
    if hasattr(args, "tap_name") and args.tap_name:
        console.log(f"[cyan]Looking for specified tap: {args.tap_name}[/cyan]")
        for t in taps:
            if t.name == args.tap_name:
                console.log(
                    f"[green]Found specified tap: {args.tap_name} (type: {t.message_type})[/green]"
                )
                # Check if it's the correct type
                if t.message_type != "synapse.BroadbandFrame":
                    console.print(
                        f"[bold red]Error: Specified tap '{args.tap_name}' has type '{t.message_type}', but only 'synapse.BroadbandFrame' is supported[/bold red]"
                    )
                    return None
                read_tap.connect(t.name)
                return read_tap

        console.print(
            f"[yellow]Warning: Specified tap '{args.tap_name}' not found, falling back to auto-selection[/yellow]"
        )

    # Auto-select: get the first tap that has exact synapse.BroadbandFrame type
    console.log("[cyan]Auto-selecting first synapse.BroadbandFrame tap[/cyan]")
    for t in taps:
        if t.message_type == "synapse.BroadbandFrame":
            console.log(f"[green]Found synapse.BroadbandFrame tap: {t.name}[/green]")
            read_tap.connect(t.name)
            return read_tap

    console.print("[bold red]No synapse.BroadbandFrame tap found[/bold red]")
    return None


def read(args):
    console = Console()

    # Make sure we can actually get to this device
    try:
        config = load_device_config(args.config, console)
    except Exception as e:
        console.print(f"[bold red]Failed to load device configuration: {e}[/bold red]")
        return

    # Create the device object
    device = syn.Device(args.uri, args.verbose)
    device_name = device.get_name()
    console.log(f"[green]Connected to {device_name}[/green]")

    # If user just wants to list taps, do that and exit
    if hasattr(args, "list_taps") and args.list_taps:
        list_available_taps(args, device, console)
        return

    # Apply the configuration to the device
    if not configure_device(device, config, console):
        console.print("[bold red]Failed to configure device[/bold red]")
        return

    # If we got this far and they want to save things, we need to make sure they have a place to save
    if args.output:
        if not setup_output(args, console):
            console.print("[bold red]Failed to setup output[/bold red]")
            return

    # Start the device
    if not start_device(device, console):
        console.print("[bold red]Failed to start device[/bold red]")
        return

    # With the device running, get the tap for us to connect to
    broadband_tap = get_broadband_tap(args, device, console)
    if not broadband_tap:
        console.print("[bold red]Failed to get broadband tap[/bold red]")
        return

    # Detect stream parameters from the first message
    sample_rate, available_channels, first_frame = detect_stream_parameters(
        broadband_tap, console
    )
    if sample_rate is None:
        console.print("[bold red]Failed to detect stream parameters[/bold red]")
        return

    # Setup our HDF5 writer if output is requested
    writer = None
    if args.output:
        writer = BroadbandFrameWriter(args.output)
        writer.set_attributes(sample_rate_hz=sample_rate, channels=available_channels)
        writer.start()

    # Setup plotter if requested
    plotter = None
    if args.plot:
        try:
            from synapse.cli.synapse_plotter import create_broadband_plotter

            plotter = create_broadband_plotter(
                sample_rate_hz=sample_rate,
                window_size_seconds=5,
                channel_ids=available_channels,
            )
            plotter.start()
            console.log(
                f"[green]Started real-time plotter with {len(available_channels)} channels available[/green]"
            )
        except ImportError as e:
            console.print(
                f"[bold red]Failed to import plotter (missing dearpygui?): {e}[/bold red]"
            )
            return

    # Setup stream monitor
    monitor = StreamMonitor(console)
    monitor.start()

    try:
        # Use batch streaming for better throughput
        with Live(monitor.get_current_stats(), refresh_per_second=4) as live:
            # Process the first frame that we already read for parameter detection
            if first_frame:
                if writer:
                    writer.put(first_frame)
                if plotter:
                    plotter.put(first_frame)
                monitor.put(first_frame)

            # Continue with batch streaming for remaining frames
            for message_batch in broadband_tap.stream_batch(batch_size=10):
                frames = []
                for message in message_batch:
                    frame = BroadbandFrame()
                    frame.ParseFromString(message)
                    frames.append(frame)

                    # Send to monitor (non-blocking)
                    monitor.put(frame)
                    if plotter:
                        plotter.put(frame)

                # Batch write for better performance
                if writer and frames:
                    writer.put_batch(frames)

                live.update(monitor.get_current_stats())

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping data collection...[/yellow]")
    finally:
        if writer:
            writer.stop()
        if plotter:
            plotter.stop()
        if monitor:
            monitor.stop()
        if args.output:
            console.print(f"[green]Data saved to {args.output}[/green]")
        if args.plot:
            console.print("[green]Plotter stopped[/green]")
