import os
import queue
import threading
import time
import h5py
from datetime import datetime
import numpy as np

import synapse as syn
from synapse.api.status_pb2 import DeviceState, StatusCode
from synapse.client.taps import Tap
from synapse.utils.proto import load_device_config
from synapse.api.datatype_pb2 import BroadbandFrame

from rich.console import Console


class DiskWriter:
    def __init__(self, output_dir: str, buffer_size: int = 1024 * 1024):
        self.output_dir = output_dir
        self.buffer_size = buffer_size
        self.data_queue = queue.Queue(maxsize=1000)  # Prevent unbounded memory growth
        self.stop_event = threading.Event()
        self.writer_thread = None

    def start(self):
        """Start the writer thread"""
        self.writer_thread = threading.Thread(target=self._write_loop)
        self.writer_thread.start()

    def stop(self):
        """Stop the writer thread and wait for it to finish"""
        self.stop_event.set()
        if self.writer_thread:
            self.writer_thread.join()

    def put(self, data: BroadbandFrame):
        """Add data to the write queue"""
        try:
            self.data_queue.put(data, block=False)
        except queue.Full:
            # If queue is full, we'll drop the oldest data
            try:
                self.data_queue.get_nowait()
                self.data_queue.put(data, block=False)
            except queue.Empty:
                pass

    def _write_loop(self):
        """Main writing loop that consumes data from the queue"""
        filename = os.path.join(self.output_dir, f"data_{int(time.time())}.dat")
        with open(filename, "wb", buffering=self.buffer_size) as f:
            while not self.stop_event.is_set() or not self.data_queue.empty():
                try:
                    data = self.data_queue.get(timeout=1)
                    # Write binary data directly
                    print(data)
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Error writing data: {e}")
                    continue


class BroadbandFrameWriter:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.data_queue = queue.Queue(maxsize=1000)
        self.stop_event = threading.Event()
        self.writer_thread = None
        
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
        # Create frame data dataset as a 1D array of variable length arrays
        self.frame_data_dataset = self.file.create_dataset(
            "/acquisition/ElectricalSeries",
            shape=(0,),
            maxshape=(None,),
            dtype=h5py.vlen_dtype(np.dtype('int32'))
        )
        
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
        """Add frame to the write queue"""
        try:
            self.data_queue.put(frame, block=False)
        except queue.Full:
            # If queue is full, we'll drop the oldest data
            try:
                self.data_queue.get_nowait()
                self.data_queue.put(frame, block=False)
            except queue.Empty:
                pass
                
    def _write_loop(self):
        """Main writing loop that consumes data from the queue"""
        while not self.stop_event.is_set() or not self.data_queue.empty():
            try:
                frame = self.data_queue.get(timeout=1)
                
                # Resize datasets
                current_size = self.timestamp_dataset.shape[0]
                new_size = current_size + 1
                
                self.timestamp_dataset.resize(new_size, axis=0)
                self.sequence_dataset.resize(new_size, axis=0)
                self.frame_data_dataset.resize(new_size, axis=0)
                
                # Write data
                self.timestamp_dataset[current_size] = frame.timestamp_ns
                self.sequence_dataset[current_size] = frame.sequence_number
                # Write frame data as a variable length array
                self.frame_data_dataset[current_size] = frame.frame_data
                
                # Flush periodically
                if new_size % 1000 == 0:
                    print(f"Flushed {new_size} frames")
                    self.flush()
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error writing data: {e}")
                continue
                
    def flush(self):
        """Flush all datasets to disk"""
        self.timestamp_dataset.flush()
        self.sequence_dataset.flush()
        self.frame_data_dataset.flush()
        self.file.flush()


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


def get_broadband_tap(args, device, console):
    read_tap = Tap(args.uri, args.verbose)
    taps = read_tap.list_taps()

    # Just get the first tap that has BroadbandFrame as the type
    for t in taps:
        if "BroadbandFrame" in t.message_type:
            read_tap.connect(t.name)
            return read_tap

    console.print("[bold red]No BroadbandFrame tap found[/bold red]")
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

    # Setup our HDF5 writer if output is requested
    writer = None
    if args.output:
        writer = BroadbandFrameWriter(args.output)
        # Get sample rate and channels from config
        # broadband_node = next((n for n in config.nodes if n.type == NodeType.kBroadbandSource), None)
        writer.set_attributes(sample_rate_hz=32000, channels=list(range(256)))

        writer.start()

    try:
        # Now we need to start the streaming
        frame = BroadbandFrame()
        with console.status("Streaming data...", spinner="bouncingBall"):
            for message in broadband_tap.stream():
                frame.ParseFromString(message)
                if writer:
                    writer.put(frame)
                else:
                    print(frame)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping data collection...[/yellow]")
    finally:
        if writer:
            writer.stop()
            console.print(f"[green]Data saved to {args.output}[/green]")
