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
from rich.layout import Layout
from rich.panel import Panel

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
        self.queue_overflow_drops = 0  # Track frames dropped due to queue being full
        self.queue = queue.Queue(maxsize=10000)
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
        self.queue_overflow_drops = 0
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
            self.queue_overflow_drops += 1

    def put_batch(self, frames: list):
        """Add multiple frames to monitoring queue efficiently (non-blocking)"""
        for frame in frames:
            try:
                self.queue.put(frame, block=False)
            except queue.Full:
                # Drop frame if queue is full to prevent blocking
                # Only break if queue is full to avoid flooding
                self.queue_overflow_drops += 1
                break

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

    def get_current_stats(self) -> dict:
        """Get current statistics as dictionary"""
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

        return {
            "messages": self.message_count,
            "rate": rate,
            "dropped": self.total_dropped,
            "queue_drops": self.queue_overflow_drops,
            "loss_percent": loss_percent,
            "runtime": current_time - self.start_time,
        }


class BroadbandFrameWriter:
    """
    Threaded HDF5 writer for broadband data streams

    Features:
    - Single writer thread with bounded queue (prevents blocking the reader)
    - Non-blocking puts with frame dropping if queue is full
    - Batch writes to HDF5 for better I/O performance
    - Compressed datasets to reduce disk space and I/O
    - Periodic flushes for optimal performance
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.data_queue = queue.Queue(maxsize=32000)
        self.stop_event = threading.Event()
        self.writer_thread = None

        # Stats tracking - separate queued vs actually written
        self.start_time = time.time()
        self.frames_queued = 0  # Frames successfully added to queue
        self.samples_queued = 0  # Samples successfully added to queue
        self.frames_written = 0  # Frames actually written to disk
        self.samples_written = 0  # Samples actually written to disk
        self.last_sequence = 0
        self.dropped_frames = 0  # Missing sequence numbers in stream
        self.queue_overflow_drops = 0  # Frames dropped due to queue being full
        self.write_errors = 0  # Count of write errors
        self.last_write_error = None  # Last write error message

        # Create HDF5 file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(output_dir, f"broadband_data_{timestamp}.h5")
        self.file = h5py.File(self.filename, "w")

        # Create datasets with chunking and compression for better performance
        self.timestamp_dataset = self.file.create_dataset(
            "/acquisition/timestamp",
            shape=(0,),
            maxshape=(None,),
            dtype="uint64",
            chunks=True,
            compression="gzip",
            compression_opts=1,  # Fast compression
        )
        self.sequence_dataset = self.file.create_dataset(
            "/acquisition/sequence_number",
            shape=(0,),
            maxshape=(None,),
            dtype="uint64",
            chunks=True,
            compression="gzip",
            compression_opts=1,
        )
        self.frame_data_dataset = self.file.create_dataset(
            "/acquisition/ElectricalSeries",
            shape=(0,),
            maxshape=(None,),
            dtype="int32",
            chunks=True,
            compression="gzip",
            compression_opts=1,
        )

    def get_stats(self):
        """Get current statistics"""
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return {
                "frames_queued_per_sec": 0,
                "samples_queued_per_sec": 0,
                "frames_written_per_sec": 0,
                "samples_written_per_sec": 0,
                "total_frames_queued": 0,
                "total_samples_queued": 0,
                "total_frames_written": 0,
                "total_samples_written": 0,
                "dropped_frames": 0,
                "queue_overflow_drops": 0,
                "write_errors": 0,
                "last_sequence": 0,
                "queue_size": 0,
                "queue_utilization": 0.0,
                "memory_pressure": "Low",
                "write_lag": 0,
                "last_write_error": None,
            }

        queue_size = self.data_queue.qsize()
        write_lag = self.frames_queued - self.frames_written

        return {
            "frames_queued_per_sec": self.frames_queued / elapsed,
            "samples_queued_per_sec": self.samples_queued / elapsed,
            "frames_written_per_sec": self.frames_written / elapsed,
            "samples_written_per_sec": self.samples_written / elapsed,
            "total_frames_queued": self.frames_queued,
            "total_samples_queued": self.samples_queued,
            "total_frames_written": self.frames_written,
            "total_samples_written": self.samples_written,
            "dropped_frames": self.dropped_frames,
            "queue_overflow_drops": self.queue_overflow_drops,
            "write_errors": self.write_errors,
            "last_sequence": self.last_sequence,
            "queue_size": queue_size,
            "queue_utilization": queue_size / self.data_queue.maxsize,
            "memory_pressure": "High"
            if queue_size > 800
            else "Medium"
            if queue_size > 500
            else "Low",
            "write_lag": write_lag,
            "last_write_error": self.last_write_error,
        }

    def set_attributes(
        self, sample_rate_hz: float, channels: list, session_description: str = ""
    ):
        """Set HDF5 attributes"""
        self.file.attrs["sample_rate_hz"] = sample_rate_hz
        if session_description:
            self.file.attrs["session_description"] = session_description
        self.file.attrs["session_start_time"] = datetime.now().isoformat()

        device_group = self.file.create_group("general/device")
        device_group.attrs["device_type"] = "SciFi"

        electrodes_group = self.file.create_group(
            "general/extracellular_ephys/electrodes"
        )
        electrodes_group.create_dataset("id", data=channels, dtype="uint32")

    def start(self):
        """Start the writer thread"""
        self.stop_event.clear()
        self.writer_thread = threading.Thread(
            target=self._write_loop, name="HDF5Writer"
        )
        self.writer_thread.start()

    def stop(self):
        """Stop the writer thread and wait for it to finish"""
        self.stop_event.set()
        if self.writer_thread:
            self.writer_thread.join()
        self.file.close()

    def put(self, frame: BroadbandFrame):
        """Add frame to write queue (non-blocking)"""
        # Try to put in queue first, drop if full (non-blocking)
        try:
            self.data_queue.put(frame, block=False)

            # Only update stats for frames that actually made it into the queue
            self.frames_queued += 1
            self.samples_queued += len(frame.frame_data)

            # Check for dropped frames in the data stream (not queue drops)
            if self.last_sequence != 0:
                expected_sequence = self.last_sequence + 1
                if frame.sequence_number != expected_sequence:
                    self.dropped_frames += frame.sequence_number - expected_sequence
            self.last_sequence = frame.sequence_number

        except queue.Full:
            # Queue is full, drop this frame to prevent blocking the reader
            # Note: This is a queue overflow drop, not a network/source drop
            self.queue_overflow_drops += 1

    def put_batch(self, frames: list):
        """Add multiple frames efficiently"""
        for frame in frames:
            self.put(frame)

    def _write_loop(self):
        frame_buffer = []
        buffer_size = 1000
        last_flush_time = time.time()

        while not self.stop_event.is_set() or not self.data_queue.empty():
            try:
                # Get frame from queue with timeout
                frame = self.data_queue.get(timeout=0.5)
                frame_buffer.append(frame)

                current_time = time.time()
                # Write buffer if it's full or if enough time has passed
                if len(frame_buffer) >= buffer_size or (
                    frame_buffer and current_time - last_flush_time > 1.0
                ):
                    self._write_buffer(frame_buffer)
                    frame_buffer = []
                    last_flush_time = current_time

            except queue.Empty:
                current_time = time.time()
                # Flush any remaining data if timeout occurred
                if frame_buffer and current_time - last_flush_time > 1.0:
                    self._write_buffer(frame_buffer)
                    frame_buffer = []
                    last_flush_time = current_time
                continue
            except Exception as e:
                self.write_errors += 1
                self.last_write_error = str(e)
                print(f"Error in writer thread: {e}")
                continue

        # Write any remaining frames when stopping
        if frame_buffer:
            self._write_buffer(frame_buffer)

    def _write_buffer(self, frame_buffer: list):
        """Write buffered frames to HDF5"""
        if not frame_buffer:
            return

        try:
            # Get current dataset sizes
            current_timestamp_size = self.timestamp_dataset.shape[0]
            current_frame_size = self.frame_data_dataset.shape[0]

            num_frames = len(frame_buffer)
            samples_per_frame = len(frame_buffer[0].frame_data)

            # Resize datasets
            new_timestamp_size = current_timestamp_size + num_frames
            new_frame_size = current_frame_size + (num_frames * samples_per_frame)

            self.timestamp_dataset.resize(new_timestamp_size, axis=0)
            self.sequence_dataset.resize(new_timestamp_size, axis=0)
            self.frame_data_dataset.resize(new_frame_size, axis=0)

            # Write data in batch
            timestamps = []
            sequences = []
            all_frame_data = []

            for frame in frame_buffer:
                timestamps.append(frame.timestamp_ns)
                sequences.append(frame.sequence_number)
                all_frame_data.extend(frame.frame_data)

            # Write all data at once (more efficient)
            self.timestamp_dataset[current_timestamp_size:new_timestamp_size] = (
                timestamps
            )
            self.sequence_dataset[current_timestamp_size:new_timestamp_size] = sequences
            self.frame_data_dataset[current_frame_size:new_frame_size] = all_frame_data

            # Update written stats AFTER successful write
            self.frames_written += num_frames
            self.samples_written += len(all_frame_data)

            # Flush to disk periodically
            if current_timestamp_size % 10000 == 0:
                self.file.flush()

        except Exception as e:
            self.write_errors += 1
            self.last_write_error = str(e)
            print(f"Error writing buffer to HDF5: {e}")


def create_combined_display(monitor, writer=None) -> Layout:
    """Create a combined display showing both monitor and writer statistics"""
    layout = Layout()

    # Create monitor stats
    monitor_stats = monitor.get_current_stats()
    monitor_text = Text()
    monitor_text.append("Stream Monitor\n", style="bold cyan")
    monitor_text.append(f"Messages: {monitor_stats['messages']:,} ", style="cyan")
    monitor_text.append(f"({monitor_stats['rate']:.1f}/s)\n", style="green")
    monitor_text.append(f"Dropped: {monitor_stats['dropped']:,} ", style="red")
    monitor_text.append(
        f"Queue Drops: {monitor_stats['queue_drops']:,}\n", style="magenta"
    )
    monitor_text.append(f"Loss: {monitor_stats['loss_percent']:.2f}% ", style="yellow")
    monitor_text.append(f"Runtime: {monitor_stats['runtime']:.1f}s", style="blue")

    if writer:
        writer_stats = writer.get_stats()
        writer_text = Text()
        writer_text.append("HDF5 Writer\n", style="bold yellow")

        # Queue status
        util_color = (
            "green"
            if writer_stats["queue_utilization"] < 0.5
            else "yellow"
            if writer_stats["queue_utilization"] < 0.8
            else "red"
        )
        writer_text.append(
            f"Queue: {writer_stats['queue_size']}/{writer.data_queue.maxsize} ",
            style=util_color,
        )
        writer_text.append(
            f"({writer_stats['queue_utilization']:.1%})\n", style=util_color
        )

        # Write performance
        write_lag = writer_stats["write_lag"]
        lag_color = (
            "green" if write_lag < 50 else "yellow" if write_lag < 200 else "red"
        )
        writer_text.append(
            f"Queued: {writer_stats['total_frames_queued']:,} frames\n", style="cyan"
        )
        writer_text.append(
            f"Written: {writer_stats['total_frames_written']:,} frames\n", style="green"
        )
        writer_text.append(f"Write Lag: {write_lag:,} frames\n", style=lag_color)
        writer_text.append(
            f"Write Rate: {writer_stats['frames_written_per_sec']:.1f}/s\n",
            style="green",
        )

        # Error tracking
        if writer_stats["write_errors"] > 0:
            writer_text.append(
                f"Write Errors: {writer_stats['write_errors']}\n", style="bold red"
            )
            if writer_stats["last_write_error"]:
                error_msg = (
                    writer_stats["last_write_error"][:50] + "..."
                    if len(writer_stats["last_write_error"]) > 50
                    else writer_stats["last_write_error"]
                )
                writer_text.append(f"Last Error: {error_msg}\n", style="red")
        else:
            writer_text.append("Write Errors: 0\n", style="green")

        # Memory pressure
        pressure_color = (
            "green"
            if writer_stats["memory_pressure"] == "Low"
            else "yellow"
            if writer_stats["memory_pressure"] == "Medium"
            else "red"
        )
        writer_text.append(
            f"Memory: {writer_stats['memory_pressure']}", style=pressure_color
        )

        # Split layout to show both
        layout.split_row(
            Layout(Panel(monitor_text, title="Stream Monitor", border_style="cyan")),
            Layout(Panel(writer_text, title="HDF5 Writer", border_style="yellow")),
        )
    else:
        # Only monitor stats
        layout.add_split(
            Layout(Panel(monitor_text, title="Stream Monitor", border_style="cyan"))
        )

    return layout


def create_status_table(writer) -> Table:
    """Create a status table for display"""
    stats = writer.get_stats()
    table = Table(title="Streaming Status")

    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Frames/sec", f"{stats['frames_written_per_sec']:.1f}")
    table.add_row("Samples/sec", f"{stats['samples_written_per_sec']:.1f}")
    table.add_row("Total Frames", str(stats["total_frames_written"]))
    table.add_row("Total Samples", str(stats["total_samples_written"]))
    table.add_row("Dropped Frames", str(stats["dropped_frames"]))
    table.add_row("Queue Overflow Drops", str(stats["queue_overflow_drops"]))
    table.add_row("Last Sequence", str(stats["last_sequence"]))

    # Add queue health information
    utilization = stats["queue_utilization"]
    util_color = (
        "green" if utilization < 0.5 else "yellow" if utilization < 0.8 else "red"
    )

    max_size = writer.data_queue.maxsize
    table.add_row(
        "Queue Usage",
        f"{stats['queue_size']}/{max_size} ({utilization:.1%})",
        style=util_color,
    )

    # Add memory pressure indicator
    pressure_color = (
        "green"
        if stats["memory_pressure"] == "Low"
        else "yellow"
        if stats["memory_pressure"] == "Medium"
        else "red"
    )
    table.add_row("Memory Pressure", stats["memory_pressure"], style=pressure_color)

    return table


def add_commands(subparsers):
    read_parser = subparsers.add_parser(
        "read", help="Read from a device's Broadband Tap and save to HDF5"
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
    read_parser.add_argument(
        "--duration",
        type=float,
        help="Duration in seconds to stream data (if not specified, streams until Ctrl+C)",
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


def stop_device(device, console):
    with console.status("Stopping device...", spinner="bouncingBall"):
        stop_status = device.stop_with_status()
        if stop_status.code != StatusCode.kOk:
            console.print(
                f"[bold red]Failed to stop device: {stop_status.message}[/bold red]"
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
        first_message = broadband_tap.read(timeout_ms=5000)
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


def create_status_line(monitor, writer=None) -> Text:
    """Create a single status line with all the important metrics"""
    monitor_stats = monitor.get_current_stats()

    # Stream monitor stats
    text = Text()
    text.append(f"Messages: {monitor_stats['messages']:,} ", style="cyan")
    text.append(f"({monitor_stats['rate']:.1f}/s) ", style="green")
    text.append(f"Dropped: {monitor_stats['dropped']:,} ", style="red")
    text.append(f"Queue Drops: {monitor_stats['queue_drops']:,} ", style="magenta")
    text.append(f"Loss: {monitor_stats['loss_percent']:.2f}% ", style="yellow")
    text.append(f"Runtime: {monitor_stats['runtime']:.1f}s", style="blue")

    if writer:
        writer_stats = writer.get_stats()
        text.append(" | ", style="dim")
        text.append(
            f"Written: {writer_stats['total_frames_written']:,} ", style="yellow"
        )
        text.append(f"({writer_stats['frames_written_per_sec']:.1f}/s) ", style="green")
        text.append(
            f"Queue: {writer_stats['queue_size']}/{writer.data_queue.maxsize}",
            style="cyan",
        )

    return text


def stream_data(broadband_tap, writer, plotter, monitor, first_frame, console, args):
    """Simple streaming function using threaded writer"""
    duration_exceeded = False
    start_time = time.time()

    try:
        console.print("[cyan]Starting data streaming... (Ctrl+C to stop)[/cyan]")

        # Process the first frame that we already read for parameter detection
        if first_frame:
            if writer:
                writer.put(first_frame)
            if plotter:
                plotter.put(first_frame)
            monitor.put(first_frame)

        # Use live display for updating status line
        with Live(create_status_line(monitor, writer), refresh_per_second=4) as live:
            # Continue with batch streaming for remaining frames
            for message_batch in broadband_tap.stream_batch(batch_size=500):
                # Check if duration limit has been reached
                if hasattr(args, "duration") and args.duration is not None:
                    elapsed_time = time.time() - start_time
                    if elapsed_time >= args.duration:
                        duration_exceeded = True
                        console.print(
                            f"\n[yellow]Duration limit of {args.duration:.1f} seconds reached. Stopping data collection...[/yellow]"
                        )
                        break

                frames = []
                for message in message_batch:
                    frame = BroadbandFrame()
                    frame.ParseFromString(message)
                    frames.append(frame)

                # Send batch to monitor and writer for better performance
                monitor.put_batch(frames)
                if writer and frames:
                    writer.put_batch(frames)

                # Send to plotter individually (plotter might need individual frames)
                if plotter:
                    for frame in frames:
                        plotter.put(frame)

                # Update the live status line
                live.update(create_status_line(monitor, writer))

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

        # Show final duration info
        final_elapsed = time.time() - start_time
        if duration_exceeded:
            console.print(
                f"[blue]Streaming completed after {final_elapsed:.1f} seconds (duration limit reached)[/blue]"
            )
        else:
            console.print(
                f"[blue]Total streaming time: {final_elapsed:.1f} seconds[/blue]"
            )

        # Show final statistics summary
        if writer:
            final_stats = writer.get_stats()
            console.print("\n[bold cyan]Final Statistics:[/bold cyan]")
            console.print(
                f"[green]Frames Written to Disk: {final_stats['total_frames_written']:,}[/green]"
            )
            console.print(
                f"[green]Samples Written to Disk: {final_stats['total_samples_written']:,}[/green]"
            )
            console.print(
                f"[cyan]Frames Queued: {final_stats['total_frames_queued']:,}[/cyan]"
            )
            if final_stats["write_errors"] > 0:
                console.print(f"[red]Write Errors: {final_stats['write_errors']}[/red]")
                if final_stats["last_write_error"]:
                    console.print(
                        f"[red]Last Error: {final_stats['last_write_error']}[/red]"
                    )
            final_lag = final_stats["write_lag"]
            if final_lag > 0:
                console.print(
                    f"[yellow]Unwritten Frames in Queue: {final_lag:,}[/yellow]"
                )
            else:
                console.print("[green]All queued frames written to disk[/green]")


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
        console.log("[cyan]Using threaded writer for serializing data[/cyan]")

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

    # Run the streaming function
    stream_data(broadband_tap, writer, plotter, monitor, first_frame, console, args)

    # Stop the device after streaming is complete
    console.log("[cyan]Stopping device...[/cyan]")
    if not stop_device(device, console):
        console.print(
            "[bold yellow]Warning: Failed to stop device cleanly[/bold yellow]"
        )
    else:
        console.log("[green]Device stopped successfully[/green]")
