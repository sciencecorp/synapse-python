import json
import queue
import threading
import time
import traceback
import os
from typing import Optional
from operator import itemgetter
import copy
import math

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
    """
    A class to monitor and analyze packet streaming statistics including:
    - Effective receive bandwidth (Mbps)
    - Jitter (variation in packet arrival intervals)
    - Total packets received
    - Packet loss detection
    - Out-of-order packet detection
    """

    def __init__(self, print_interval=100, history_size=1000):
        # Configuration
        self.print_interval = print_interval
        self.history_size = history_size

        # Packet tracking
        self.packet_count = 0
        self.seq_number = None
        self.dropped_packets = 0
        self.out_of_order_packets = 0

        # Timing metrics
        self.start_time = None
        self.last_stats_time = None
        self.first_packet_time = None

        # Bandwidth tracking
        self.bytes_received = 0
        self.bandwidth_samples = []
        self.last_bandwidth_time = None
        self.last_bytes_received = 0

        # Jitter tracking
        self.packet_arrival_times = []
        self.packet_intervals = []

        # Stats dictionary
        self.stats = {
            "total_packets": 0,
            "dropped_packets": 0,
            "out_of_order_packets": 0,
            "drop_rate": 0.0,
            "bandwidth_mbps": 0.0,
            "jitter_ms": 0.0,
            "run_time_seconds": 0.0,
        }

    def start_monitoring(self):
        """Initialize monitoring timers"""
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        self.last_bandwidth_time = self.start_time

    def process_packet(self, header, data):
        """
        Process a single packet and update statistics

        Args:
            header: Packet header containing sequence number
            data: Packet data

        Returns:
            bool: True if packet was processed, False otherwise
        """
        if not data:
            return False

        packet_received_time = time.time()

        # Record first packet time
        if self.packet_count == 0:
            self.first_packet_time = packet_received_time
            print(
                f"First packet received at {packet_received_time - self.start_time:.3f} seconds"
            )

        # Track packet arrival for jitter calculation
        self.packet_arrival_times.append(packet_received_time)

        # Calculate packet intervals for jitter
        if len(self.packet_arrival_times) > 1:
            interval = (
                self.packet_arrival_times[-1] - self.packet_arrival_times[-2]
            ) * 1000.0  # Convert to ms
            self.packet_intervals.append(interval)

        # Update byte count for bandwidth calculation
        # Calculate exact size based on the NDTP message structure

        # Header size from NDTPHeader.STRUCT.size (1 + 1 + 8 + 2 = 12 bytes)
        # >BBQH: > (big-endian), B (unsigned char, 1 byte), B (unsigned char, 1 byte),
        # Q (unsigned long long, 8 bytes), H (unsigned short, 2 bytes)
        header_size = 12  # We know this from the struct format

        # Payload size calculation based on ElectricalBroadbandData
        payload_size = 0

        if hasattr(data, "samples"):
            # Add bytes for each channel's samples
            for ch_id, samples in data.samples:
                # Calculate sample size from bit_width
                if hasattr(data, "bit_width"):
                    bytes_per_sample = math.ceil(data.bit_width / 8)
                else:
                    bytes_per_sample = 4  # Default to 4 bytes if bit_width unknown

                # Calculate this channel's data size
                channel_data_size = len(samples) * bytes_per_sample

                # Add overhead for channel metadata (ID, length indicator, etc.)
                # This is an estimate; adjust based on actual protocol
                channel_overhead = 8  # Typically a few bytes for channel ID and length

                payload_size += channel_data_size + channel_overhead

            # Add general payload overhead (type indicators, length fields, etc.)
            # This is an estimate; adjust based on actual protocol
            payload_size += 16  # General payload metadata
        else:
            # Fallback if we can't determine the payload structure
            payload_size = 1024  # Assume 1KB payload

        packet_size = header_size + payload_size
        self.bytes_received += packet_size

        self.packet_count += 1

        # Sequence number checking for packet loss/ordering
        if self.seq_number is None:
            self.seq_number = header.seq_number
        else:
            expected = (self.seq_number + 1) % (2**16)
            if header.seq_number != expected:
                if header.seq_number > expected:
                    # Packet loss scenario
                    lost = (header.seq_number - expected) % (2**16)
                    self.dropped_packets += lost
                    print(
                        f"Packet loss detected: expected {expected}, got {header.seq_number}, lost {lost} packets"
                    )
                else:
                    # Out of order scenario
                    self.out_of_order_packets += 1
                    print(
                        f"Out of order packet: expected {expected}, got {header.seq_number}"
                    )

            self.seq_number = header.seq_number

        # Limit history sizes to prevent memory growth
        if len(self.packet_arrival_times) > self.history_size:
            self.packet_arrival_times = self.packet_arrival_times[-self.history_size :]
        if len(self.packet_intervals) > self.history_size:
            self.packet_intervals = self.packet_intervals[-self.history_size :]

        return True

    def calculate_bandwidth(self):
        """Calculate current bandwidth in Mbps"""
        current_time = time.time()
        time_delta = current_time - self.last_bandwidth_time

        # Only calculate bandwidth if enough time has passed (avoid division by small numbers)
        if time_delta >= 0.5:  # Calculate bandwidth every 500ms minimum
            bytes_delta = self.bytes_received - self.last_bytes_received

            # Calculate bandwidth in Mbps (megabits per second)
            # bytes_delta * 8 converts bytes to bits, / 1_000_000 converts to megabits
            bandwidth_mbps = (bytes_delta * 8) / (time_delta * 1_000_000)

            self.bandwidth_samples.append(bandwidth_mbps)
            # Limit bandwidth history
            if len(self.bandwidth_samples) > self.history_size:
                self.bandwidth_samples = self.bandwidth_samples[-self.history_size :]

            self.last_bandwidth_time = current_time
            self.last_bytes_received = self.bytes_received

            return bandwidth_mbps

        # If not enough time has passed, return the last calculated bandwidth or 0
        return self.bandwidth_samples[-1] if self.bandwidth_samples else 0

    def calculate_jitter(self):
        """Calculate jitter in milliseconds"""
        if len(self.packet_intervals) < 2:
            return 0

        # Jitter is the mean deviation in packet interval times
        # RFC 3550 defines jitter as the mean deviation of the packet spacing
        jitter = 0

        # Calculate mean deviation
        for i in range(1, len(self.packet_intervals)):
            jitter += abs(self.packet_intervals[i] - self.packet_intervals[i - 1])

        return jitter / (len(self.packet_intervals) - 1)

    def print_periodic_stats(self, force=False):
        """
        Print periodic statistics if interval has elapsed or if forced

        Args:
            force: Force printing stats regardless of interval

        Returns:
            bool: True if stats were printed, False otherwise
        """
        current_time = time.time()
        stats_interval = current_time - self.last_stats_time

        if (
            not force
            and self.packet_count % self.print_interval != 0
            and stats_interval < 5.0
        ):
            return False

        # Calculate summary statistics
        run_time = current_time - self.start_time

        # Calculate bandwidth
        bandwidth_mbps = self.calculate_bandwidth()

        # Calculate jitter
        jitter_ms = self.calculate_jitter()

        # Update stats dictionary
        self.stats["total_packets"] = self.packet_count
        self.stats["dropped_packets"] = self.dropped_packets
        self.stats["out_of_order_packets"] = self.out_of_order_packets
        self.stats["drop_rate"] = (
            (self.dropped_packets / (self.packet_count + self.dropped_packets)) * 100
            if self.packet_count + self.dropped_packets > 0
            else 0
        )
        self.stats["bandwidth_mbps"] = bandwidth_mbps
        self.stats["jitter_ms"] = jitter_ms
        self.stats["run_time_seconds"] = run_time

        # Pretty print stats
        print("\n--- Packet Statistics ---")
        print(f"Run time: {run_time:.2f} seconds")
        print(f"Total packets: {self.packet_count}")
        print(f"Effective bandwidth: {bandwidth_mbps:.2f} Mbps")
        print(
            f"Dropped packets: {self.dropped_packets} ({self.stats['drop_rate']:.2f}%)"
        )
        print(f"Out-of-order packets: {self.out_of_order_packets}")
        print(f"Jitter: {jitter_ms:.3f} ms")

        throughput_packets = self.packet_count / run_time if run_time > 0 else 0
        print(f"Packet throughput: {throughput_packets:.2f} packets/second")

        print("-----------------------\n")

        # Reset for next interval
        self.last_stats_time = current_time
        return True

    def print_final_stats(self):
        """Print final comprehensive statistics"""
        end_time = time.time()
        total_runtime = end_time - self.start_time

        # Calculate final bandwidth using total bytes received
        avg_bandwidth_mbps = (self.bytes_received * 8) / (total_runtime * 1_000_000)

        print("\n=== Final Statistics ===")
        print(f"Total runtime: {total_runtime:.2f} seconds")
        print(f"Total packets received: {self.packet_count}")
        print(f"Total bytes received: {self.bytes_received:,} bytes")
        print(f"Average bandwidth: {avg_bandwidth_mbps:.2f} Mbps")
        print(
            f"Packet throughput: {self.packet_count / total_runtime:.2f} packets/second"
        )
        print(
            f"Dropped packets: {self.dropped_packets} ({(self.dropped_packets / (self.packet_count + self.dropped_packets)) * 100:.2f}% loss)"
        )
        print(f"Out-of-order packets: {self.out_of_order_packets}")

        if self.packet_intervals:
            avg_jitter = self.calculate_jitter()
            print(f"Average jitter: {avg_jitter:.3f} ms")

        # Print max bandwidth observed
        if self.bandwidth_samples:
            max_bandwidth = max(self.bandwidth_samples)
            print(f"Peak bandwidth: {max_bandwidth:.2f} Mbps")

        print("=====================")

    def get_stats_dict(self):
        """Return a dictionary with all current statistics"""
        # Update with latest values before returning
        self.calculate_bandwidth()

        stats = self.stats.copy()

        # Add additional derived statistics
        stats["peak_bandwidth_mbps"] = (
            max(self.bandwidth_samples) if self.bandwidth_samples else 0
        )
        stats["avg_bandwidth_mbps"] = (
            sum(self.bandwidth_samples) / len(self.bandwidth_samples)
            if self.bandwidth_samples
            else 0
        )
        stats["total_bytes_received"] = self.bytes_received
        stats["packet_throughput"] = (
            self.packet_count / self.stats["run_time_seconds"]
            if self.stats["run_time_seconds"] > 0
            else 0
        )

        return stats


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

        if not device.configure(config):
            raise ValueError("Failed to configure device")

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
    packet_count = 0
    seq_number = None
    dropped_packets = 0
    start = time.time()
    # print_interval = 1000

    print(
        f"Reading packets for duration {duration} seconds"
        if duration
        else "Reading packets..."
    )

    monitor = PacketMonitor()
    monitor.start_monitoring()

    while True:
        header, data = node.read()
        if not data:
            continue
        monitor.process_packet(header, data)

        packet_count += 1

        # Detect dropped packets via seq_number
        if seq_number is None:
            seq_number = header.seq_number
        else:
            expected = (seq_number + 1) % (2**16)
            if header.seq_number != expected:
                dropped_packets += header.seq_number - expected
            seq_number = header.seq_number

        # Always add the data to the writer queues
        q.put(data)
        if plot_q:
            plot_q.put(copy.deepcopy(data))

        monitor.print_periodic_stats()

        # if packet_count == 1:
        #     print(f"First packet received at {time.time() - start:.2f} seconds")

        # if packet_count % print_interval == 0:
        #     print(
        #         f"Recieved {packet_count} packets in {time.time() - start} seconds. Dropped {dropped_packets} packets ({(dropped_packets / packet_count) * 100}%)"
        #     )
        if duration and (time.time() - start) > duration:
            break

    monitor.print_final_stats()

    # print(
    #     f"Recieved {packet_count} packets in {time.time() - start} seconds. Dropped {dropped_packets} packets ({(dropped_packets / packet_count) * 100}%)"
    # )


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
