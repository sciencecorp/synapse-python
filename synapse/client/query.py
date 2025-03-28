#!/usr/bin/env python3
import csv
import numpy as np
import time
import sys
import synapse as syn
from synapse.api.node_pb2 import NodeType
from synapse.api.query_pb2 import QueryRequest, StreamQueryRequest, SelfTestQuery
from synapse.api.synapse_pb2 import DeviceConfiguration
from google.protobuf.json_format import Parse

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.console import Console

import matplotlib.pyplot as plt


class StreamingQueryClient:
    def __init__(self, uri, verbose=False, plot=False):
        self.uri = uri
        self.verbose = verbose
        self.plot = plot
        self.console = Console()

        self.device = syn.Device(self.uri, self.verbose)
        if self.verbose:
            info = self.device.info()
            self.console.log(info)

    def stream_query(self, request):
        query_type = request.request.query_type
        if query_type == QueryRequest.kImpedance:
            return self.handle_impedance_stream(request)
        elif query_type == QueryRequest.kSelfTest:
            return self.handle_self_test_stream(request)
        else:
            self.console.log(f"[bold red]Unknown stream request: {query_type}")
            return False

    def handle_self_test_stream(self, request):
        query = request.request.self_test_query
        if not query:
            self.console.log("[bold red] Invalid query for self test stream")
            return False

        self.console.log("[cyan] Starting self test stream")

        all_responses = []
        with self.console.status(
            "Running Self Test", spinner="bouncingBall", spinner_style="green"
        ):
            for response in self.device.stream_query(request):
                if not response:
                    self.console.log("Stream is complete")
                    break

                if response.code != 0 or not response.self_test:
                    self.console.log(
                        f"[bold red] Failed self test, why: {response.message}"
                    )
                    return False

                all_responses.append(response.self_test)

        if not all_responses:
            return False

        table = Table(title="Self Test Results")
        table.add_column("Test", justify="right")
        table.add_column("Passed?", justify="right")
        table.add_column("Report", justify="right")

        for response in all_responses:
            for test in response.tests:
                print(test)

    def handle_impedance_stream(self, request):
        query = request.request.impedance_query
        if not query:
            self.console.log("[bold red] Invalid query for impedance stream")
            return False

        electrode_count = len(query.electrode_ids)
        self.console.log(
            f"[cyan] Starting impedance_stream with {electrode_count} electordes"
        )

        measurements_received = 0
        all_measurements = []
        failed_measurements = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan] Processing impedance measurements [/bold cyan]"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("Measuring impedance", total=electrode_count)

            for response in self.device.stream_query(request):
                if not response:
                    self.console.log("Stream is complete")
                    break

                # Check if this failed
                if response.code != 0 or not response.impedance:
                    failed_batch = response.impedance.measurements
                    failed_measurements.extend(failed_batch)

                    failed_ids = [m.electrode_id for m in failed_batch]
                    self.console.log(
                        f"Failed to measure impedance for {failed_ids}, why: {response.message}"
                    )
                    continue

                measurement_batch = response.impedance.measurements

                # Figure out how many we processed in this batch
                measurements_received += len(measurement_batch)
                progress.update(
                    task, completed=min(measurements_received, electrode_count)
                )

                # Add these to our batch
                all_measurements.extend(measurement_batch)

                if args.verbose:
                    for measurement in measurement_batch:
                        progress.console.print(
                            f"Electrode {measurement.electrode_id}: {measurement.magnitude}Ω"
                        )

        if all_measurements:
            self.display_impedance_results(all_measurements)
            self.save_impedance_results(all_measurements)
            if self.plot:
                self.plot_impedance_results(all_measurements)
        else:
            self.console.log("[bold red] All impedance measurements failed")

        if failed_measurements:
            failed_ids = [m.electrode_id for m in failed_measurements]
            self.console.log(f"[bold red]Failed impedance electrodes\n{failed_ids}")
        return True

    def display_impedance_results(self, measurements):
        table = Table(title="Impedance Measurements")
        table.add_column("Electorde ID", justify="right")
        table.add_column("Magnitude", justify="right")
        table.add_column("Phase", justify="right")

        for measurement in measurements:
            table.add_row(
                str(measurement.electrode_id),
                f"{measurement.magnitude:.2f}",
                f"{measurement.phase:.2f}",
            )
        self.console.print(table)

    def save_impedance_results(self, measurements):
        # just match the original implementations filename
        filename = f"impedance_measurements_{time.strftime('%Y%m%d-%H%M%S')}.csv"

        # probably won't have a duplicate file here
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Electrode ID", "Magnitude", "Phase"])
            for measurement in measurements:
                writer.writerow(
                    [measurement.electrode_id, measurement.magnitude, measurement.phase]
                )

        self.console.print(f"[green] Measurements saved to {filename}")

    def plot_impedance_results(self, measurements):
        electrode_ids = [measurement.electrode_id for measurement in measurements]

        # Convert the magnitudes to kilo ohms
        magnitudes = [measurement.magnitude / 1000 for measurement in measurements]
        phases = [measurement.phase for measurement in measurements]

        # Sort by the electrode id
        sorted_indices = np.argsort(electrode_ids)
        electrode_ids = [electrode_ids[i] for i in sorted_indices]
        magnitudes = [magnitudes[i] for i in sorted_indices]
        phases = [phases[i] for i in sorted_indices]
        fig, ax = plt.subplots(figsize=(10, 6))
        x_positions = np.arange(len(electrode_ids))

        # Add phase values as text annotations on top of each bar
        for i, (pos, y, phase) in enumerate(zip(x_positions, magnitudes, phases)):
            ax.annotate(
                f"{phase:.1f}°",
                (pos, y),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                fontsize=9,
            )

        # Add labels and title
        ax.set_xlabel("Electrode ID", fontsize=12)
        ax.set_ylabel("Impedance Magnitude (kΩ)", fontsize=12)
        ax.set_title("Electrode Impedance Measurements", fontsize=14)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(electrode_ids)
        ax.grid(axis="y", linestyle="--", alpha=0.7)

        plt.tight_layout()
        plt.show()


def load_config_from_file(path_to_config):
    try:
        with open(path_to_config, "r") as f:
            data = f.read()
            proto = Parse(data, DeviceConfiguration())
            return syn.Config.from_proto(proto)
    except Exception:
        print(f"Failed to open {path_to_config}")
        return None


def get_electrode_ids_from_config(config):
    # Check if we have a broadband config
    broadband = next(
        (n for n in config.nodes if n.type == NodeType.kBroadbandSource), None
    )
    if not broadband:
        return None
    channels = broadband.signal.electrode.channels
    return [i.electrode_id for i in channels]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stream Query Client Test")
    parser.add_argument("--uri", default="localhost:50051", help="Synapse server URI")
    parser.add_argument("--verbose", action="store_true", help="Use verbose output")
    parser.add_argument(
        "--plot", action="store_true", help="Plot the output after the run"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to the configuration with the electrode ids",
        required=True,
    )

    args = parser.parse_args()

    config_path = args.config
    config = load_config_from_file(config_path)
    if not config:
        sys.exit(1)

    electrode_ids = get_electrode_ids_from_config(config)
    if not electrode_ids:
        print("No electrode IDs present in the broadband configuration")
        sys.exit(1)

    client = StreamingQueryClient(args.uri, args.verbose, args.plot)

    # request = StreamQueryRequest(
    #     request=QueryRequest(
    #         query_type=QueryRequest.kImpedance,
    #         impedance_query=ImpedanceQuery(
    #             electrode_ids=electrode_ids
    #         )
    #     )
    # )

    request = StreamQueryRequest(
        request=QueryRequest(
            query_type=QueryRequest.kSelfTest,
            self_test_query=SelfTestQuery(peripheral_id=2),
        )
    )
    if not client.stream_query(request):
        print("Failed to stream query for device")
        sys.exit(1)
