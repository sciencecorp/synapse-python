import json
import queue
import threading
import time
import traceback
import os
from typing import Optional
from operator import itemgetter
import copy
import sys

from google.protobuf.json_format import Parse, MessageToJson

from synapse.api.node_pb2 import NodeType
from synapse.api.status_pb2 import DeviceState, StatusCode
from synapse.api.synapse_pb2 import DeviceConfiguration
import synapse as syn
import synapse.client.channel as channel
import synapse.utils.ndtp_types as ndtp_types
import synapse.cli.synapse_plotter as plotter

from rich.console import Console
from rich.pretty import pprint


class PacketMonitor:
    def __init__(self):
        # Packet tracking
        self.packet_count = 0
        self.seq_number = None
        self.dropped_packets = 0
        self.out_of_order_packets = 0

        # Timing metrics
        self.start_time = None
        self.first_packet_time = None

        # Bandwidth tracking
        self.bytes_received = 0
        self.bytes_received_in_interval = 0
        self.bandwidth_samples = []
        self.last_bandwidth_time = None
        self.last_bytes_received = 0

        # Jitter tracking
        self.last_packet_time = None
        self.last_jitter = 0
        self.avg_jitter = 0

    def start_monitoring(self):
        """Initialize monitoring timers"""
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        self.last_bandwidth_time = self.start_time

    def process_packet(self, header, data, bytes_read):
        if not data:
            return False
        packet_received_time = time.time()
        # Record first packet time
        if self.packet_count == 0:
            self.first_packet_time = packet_received_time
            self.last_packet_time = packet_received_time
            print(
                f"First packet received after {packet_received_time - self.start_time:.3f} seconds\n\n"
            )
        else:
            # Calculate jitter
            interval = packet_received_time - self.last_packet_time
            # Update jitter using RFC 3550 algorithm (smoother than just max-min)
            # https://datatracker.ietf.org/doc/html/rfc3550#appendix-A.8
            if self.packet_count > 1:
                jitter_diff = abs(interval - self.last_jitter)
                self.avg_jitter += (jitter_diff - self.avg_jitter) / 16

            # Save current values for next calculation
            self.last_jitter = interval
            self.last_packet_time = packet_received_time

        # We got a new packet
        self.packet_count += 1
        self.bytes_received += bytes_read
        self.bytes_received_in_interval += bytes_read
        # Sequence number checking for packet loss/ordering
        if self.seq_number is None:
            self.seq_number = header.seq_number
        else:
            expected = (self.seq_number + 1) % (2**16)
            if header.seq_number != expected:
                # Lost some packets
                if header.seq_number > expected:
                    lost = (header.seq_number - expected) % (2**16)
                    self.dropped_packets += lost
                else:
                    self.out_of_order_packets += 1
            self.seq_number = header.seq_number

        return True

    def print_stats(self):
        # Use carriage return to update on the same line
        sys.stdout.write("\r")

        # Drop calculation
        drop_percent = (self.dropped_packets / max(1, self.packet_count)) * 100.0
        sys.stdout.write(
            f"Dropped: {self.dropped_packets}/{self.packet_count} ({drop_percent:.1f}%) | "
        )

        # Bandwidth calcs
        now = time.time()
        dt_sec = now - self.last_bandwidth_time
        if dt_sec > 0:
            bytes_per_second = self.bytes_received_in_interval / dt_sec
            megabits_per_second = (bytes_per_second * 8) / 1_000_000
            sys.stdout.write(f"Mbit/sec: {megabits_per_second:.1f} | ")

        # Jitter (in milliseconds)
        jitter_ms = self.avg_jitter * 1000  # Convert to ms
        sys.stdout.write(f"Jitter: {jitter_ms:.2f} ms | ")

        # Out of order
        sys.stdout.write(f"Out of Order: {self.out_of_order_packets}")

        # Flush the output to ensure it's displayed
        sys.stdout.flush()

        # Reset for the next run
        self.bytes_received_in_interval = 0
        self.last_bandwidth_time = now

        return True

    def print_final_stats(self):
        print("final")


def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str, help="IP address of Synapse device")
    a.add_argument(
        "--config",
        type=str,
        help="Configuration file",
    )
    a.add_argument(
        "--num_ch", type=int, help="Number of channels to read from, overrides config"
    )
    a.add_argument("--bin", type=bool, help="Output binary format instead of JSON")
    a.add_argument("--duration", type=int, help="Duration to read for in seconds")
    a.add_argument("--node_id", type=int, help="ID of the StreamOut node to read from")
    a.add_argument("--plot", action="store_true", help="Plot the data in real-time")
    a.add_argument("--output", type=str, help="Name of the output directory and files")
    a.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing files",
    )
    a.set_defaults(func=read)


def load_config_from_file(path):
    with open(path, "r") as f:
        data = f.read()
        proto = Parse(data, DeviceConfiguration())
        return syn.Config.from_proto(proto)


def read(args):
    console = Console()
    if not args.config and not args.node_id:
        console.print("[bold red]Either `--config` or `--node_id` must be specified.")
        return

    output_base = args.output
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    if not output_base:
        output_base = f"synapse_data_{timestamp}"
    else:
        output_base = f"{output_base}_{timestamp}"

    # Check if the output directory exists, we will make the directory later after we know the config
    if os.path.exists(output_base):
        if not args.overwrite:
            console.print(
                f"[bold red]Output directory {output_base} already exists, please specify a different output directory or use `--overwrite` to overwrite existing files"
            )
            return
        else:
            console.print(f"[bold yellow]Overwriting existing files in {output_base}")

    device = syn.Device(args.uri, args.verbose)

    with console.status(
        "Reading from Synapse Device", spinner="bouncingBall", spinner_style="green"
    ) as status:
        status.update("Requesting device info")
        info = device.info()
        if not info:
            console.print(f"[bold red]Failed to get device info from {args.uri}")
            return

    console.log(f"Got info from: {info.name}")
    if args.verbose:
        pprint(info)
        console.print("\n")

    status.update("Loading recording configuration")

    # Keep track of the sample rate in case we need to plot
    sample_rate_hz = 32000
    if args.config:
        config = load_config_from_file(args.config)
        if not config:
            console.print(f"[bold red]Failed to load config from {args.config}")
            return
        stream_out = next(
            (n for n in config.nodes if n.type == NodeType.kStreamOut), None
        )
        if not stream_out:
            console.print("[bold red]No StreamOut node found in config")
            return
        broadband = next(
            (n for n in config.nodes if n.type == NodeType.kBroadbandSource), None
        )
        if not broadband:
            console.print("[bold red]No BroadbandSource node found in config")
            return
        signal = broadband.signal
        if not signal:
            console.print("[bold red]No signal configured for BroadbandSource node")
            return

        if not signal.electrode:
            console.print(
                "[bold red]No electrode signal configured for BroadbandSource node"
            )
            return

        num_ch = len(signal.electrode.channels)
        if args.num_ch:
            num_ch = args.num_ch
            offset = 0
            channels = []
            for ch in range(offset, offset + num_ch):
                channels.append(channel.Channel(ch, 2 * ch, 2 * ch + 1))

            broadband.signal.electrode.channels = channels

        with console.status(
            "Configuring device", spinner="bouncingBall", spinner_style="green"
        ) as status:
            configure_status = device.configure_with_status(config)
            if configure_status is None:
                console.print(
                    "[bold red]Failed to configure device. Run with `--verbose` for more information."
                )
                return
            if configure_status.code == StatusCode.kInvalidConfiguration:
                console.print("[bold red]Failed to configure device.")
                console.print(f"[italic red]Why: {configure_status.message}")
                console.print("[yellow]Is there a peripheral connected to the device?")
                return
            elif configure_status.code == StatusCode.kFailedPrecondition:
                console.print("[bold red]Failed to configure device.")
                console.print(f"[italic red]Why: {configure_status.message}")
                console.print(
                    f"[yellow]If the device is already running, run `synapsectl stop {args.uri}` to stop the device and try again."
                )
                return
            console.print("[bold green]Device configured successfully")

        if info.status.state != DeviceState.kRunning:
            print("Starting device...")
            if not device.start():
                raise ValueError("Failed to start device")

        # Get the sample rate from the device
        # We need to look at the node configuration with type kBroadbandSource for the sample rate
        broadband = next(
            (n for n in config.nodes if n.type == NodeType.kBroadbandSource), None
        )
        assert broadband is not None, "No BroadbandSource node found in config"
        sample_rate_hz = broadband.sample_rate_hz

    else:
        # TODO(gilbert): Get rid of this giant if-else block
        node = next(
            (
                n
                for n in info.configuration.nodes
                if n.type == NodeType.kStreamOut and n.id == args.node_id
            ),
            None,
        )
        if node is None:
            console.print(
                "[bold red]No StreamOut node found in device configuration; please configure the device with a StreamOut node."
            )
            return

        stream_out = syn.StreamOut.from_proto(node)
        stream_out.device = device

    # We are ready to start streaming, make the output directory
    os.makedirs(output_base, exist_ok=True)

    # Copy our config that was taken from the device to the output directory
    device_info_after_config = device.info()
    if not device_info_after_config:
        console.print(f"[bold red]Failed to get device info from {args.uri}")
        return
    runtime_config = device_info_after_config.configuration
    runtime_config_json = MessageToJson(
        runtime_config, always_print_fields_with_no_presence=True
    )
    output_config_path = os.path.join(output_base, "runtime_config.json")
    with open(output_config_path, "w") as f:
        f.write(runtime_config_json)

    console.print(f"[bold green]Streaming data to {output_base}")

    status_title = (
        f"Streaming data for {args.duration} seconds"
        if args.duration
        else "Streaming data indefinitely"
    )
    console.print(status_title)

    q = queue.Queue()
    plot_q = queue.Queue() if args.plot else None

    threads = []
    stop = threading.Event()
    if args.bin:
        threads.append(
            threading.Thread(target=_binary_writer, args=(stop, q, num_ch, output_base))
        )
    else:
        threads.append(
            threading.Thread(target=_data_writer, args=(stop, q, output_base))
        )

    if args.plot:
        threads.append(
            threading.Thread(
                target=_plot_data, args=(stop, plot_q, sample_rate_hz, num_ch)
            )
        )
    for thread in threads:
        thread.start()

    try:
        read_packets(stream_out, q, plot_q, args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping read...")
        stop.set()
        for thread in threads:
            thread.join()

        if args.config:
            console.print("Stopping device...")
            if not device.stop():
                console.print("[red]Failed to stop device")
            console.print("Stopped")

    console.print("[bold green]Streaming complete")
    console.print("[cyan]================")
    console.print(f"[cyan]Output directory: {output_base}/")
    if args.bin:
        console.print(f"[cyan]{output_base}.dat")
    else:
        console.print(f"[cyan]{output_base}.jsonl")
    console.print("[cyan]================")


def read_packets(
    node: syn.StreamOut,
    q: queue.Queue,
    plot_q: queue.Queue,
    duration: Optional[int] = None,
    num_ch: int = 32,
):
    start = time.time()
    last_print_time = start

    print(
        f"Reading packets for duration {duration} seconds"
        if duration
        else "Reading packets..."
    )

    # Keep track of our statistics
    monitor = PacketMonitor()
    monitor.start_monitoring()
    while True:
        synapse_data, bytes_read = node.read()
        if synapse_data is None or bytes_read == 0:
            print("Could not read data from node")
            continue
        header, data = synapse_data
        monitor.process_packet(header, data, bytes_read)

        # Always add the data to the writer queues
        q.put(data)
        if plot_q:
            plot_q.put(copy.deepcopy(data))

        # Print every second our current statistics
        if time.time() - last_print_time > 1.0:
            monitor.print_stats()
            last_print_time = time.time()

        if duration and (time.time() - start) > duration:
            break

    monitor.print_final_stats()


def _binary_writer(stop, q, num_ch, output_base):
    filename = f"{output_base}.dat"
    full_path = os.path.join(output_base, filename)
    if filename:
        fd = open(full_path, "wb")

    channel_data = []
    while not stop.is_set() or not q.empty():
        try:
            data: ndtp_types.ElectricalBroadbandData = q.get(True, 1)
        except queue.Empty:
            continue

        try:
            for ch_id, samples in data.samples:
                channel_data.append([ch_id, samples])
                if len(channel_data) == num_ch:
                    channel_data.sort(key=itemgetter(0))
                    channel_samples = [ch_data[1] for ch_data in channel_data]
                    frames = list(zip(*channel_samples))
                    channel_data = []

                    for frame in frames:
                        for sample in frame:
                            fd.write(
                                int(sample).to_bytes(2, byteorder="little", signed=True)
                            )

        except Exception as e:
            print(f"Error processing data: {e}")
            traceback.print_exc()
            continue


def _data_writer(stop, q, output_base):
    filename = f"{output_base}.jsonl"
    full_path = os.path.join(output_base, filename)
    if filename:
        fd = open(full_path, "wb")

    while not stop.is_set() or not q.empty():
        try:
            data = q.get(True, 1)
        except queue.Empty:
            continue

        try:
            fd.write(json.dumps(data.to_list()).encode("utf-8"))
            fd.write(b"\n")

        except Exception as e:
            print(f"Error processing data: {e}")
            traceback.print_exc()
            continue


def _plot_data(stop, q, sample_rate_hz, num_channels):
    # TODO(gilbert): Make these configurable
    window_size_seconds = 3
    plotter.plot_synapse_data(
        stop, q, sample_rate_hz, num_channels, window_size_seconds
    )
