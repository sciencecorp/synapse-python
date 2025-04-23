#!/usr/bin/env python3
import asyncio
import csv
from threading import Thread
import time
import sys
import synapse as syn
from synapse.api.query_pb2 import QueryRequest, StreamQueryRequest
from google.protobuf.json_format import Parse

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel


class StreamingQueryClient:
    def __init__(self, uri, verbose=False):
        self.uri = uri
        self.verbose = verbose
        self.console = Console()

        self.device = syn.Device(self.uri, self.verbose)
        if self.verbose:
            info = self.device.info()
            self.console.log(info)

            # We tail the logs in the background with verbose set
            self.log_stop_event = asyncio.Event()
            self.new_log_event = asyncio.Event()
            self.log_thread = Thread(target=self.tail_logs_background, daemon=True)
            self.log_thread.start()

    def close(self):
        if self.log_thread.is_alive():
            self.log_stop_event.set()
            self.log_thread.join()

    def tail_logs_background(self):
        self.last_log_line = ""
        for log in self.device.tail_logs():
            if self.last_log_line != log.message:
                self.last_log_line = log.message
                self.new_log_event.set()
            if self.log_stop_event.is_set():
                break

    def stream_query(self, request):
        query_type = request.request.query_type
        try:
            if query_type == QueryRequest.kImpedance:
                return self.handle_impedance_stream(request)
            elif query_type == QueryRequest.kSelfTest:
                return self.handle_self_test_stream(request)
            else:
                self.console.log(f"[bold red]Unknown stream request: {query_type}")
                return False
        except Exception as e:
            self.console.log(f"[bold red] Uncaught exception during stream: {e}")
            return False
        except KeyboardInterrupt:
            self.console.log("[yellow] Operation cancelled by user")
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
        ) as status:
            # If we are verbose, we want to show the latest log
            stop_tailing_logs = asyncio.Event()

            def update_status():
                while not stop_tailing_logs.is_set():
                    if self.new_log_event.is_set():
                        status.update(self.last_log_line)
                        self.new_log_event.clear()

            status_thread = None
            if self.verbose:
                status_thread = Thread(target=update_status, daemon=True)
                status_thread.start()

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

            if status_thread:
                stop_tailing_logs.set()
                status_thread.join()

        if not all_responses:
            return False

        table = Table(title="Self Test Results")
        table.add_column("Test", justify="right")
        table.add_column("Passed?", justify="right")
        table.add_column("Report", justify="right")

        for response in all_responses:
            for test in response.tests:
                if test.passed:
                    table.add_row(
                        test.test_name, "[green]Passed[/green]", test.test_report
                    )
                else:
                    table.add_row(test.test_name, "[red]Failed[/red]", test.test_report)

        self.console.print(table)
        return True

    def handle_impedance_stream(self, request):
        query = request.request.impedance_query
        if not query:
            self.console.log("[bold red] Invalid query for impedance stream")
            return False

        electrode_count = len(query.electrode_ids)
        if electrode_count <= 0:
            self.console.log("[bold red] No electrodes to query")
            return False

        self.console.log(
            f"[cyan] Starting impedance_stream with {electrode_count} electordes"
        )

        measurements_received = 0
        all_measurements = []
        failed_measurements = []

        # Create a CSV file to read from at the beginning
        filename = f"impedance_measurements_{time.strftime('%Y%m%d-%H%M%S')}.csv"
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Electrode ID", "Magnitude", "Phase"])
        self.console.print(f"[green] Started saving measurements to {filename}")

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan] Processing impedance measurements [/bold cyan]"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("[cyan]({task.completed}/{task.total})[/cyan]"),
            TimeElapsedColumn(),
        )

        def get_renderable():
            if self.verbose:
                return Group(
                    Panel(
                        self.last_log_line,
                        title="Latest Device Log",
                        border_style="cyan",
                    ),
                    progress,
                )
            else:
                return progress

        with Live(get_renderable(), refresh_per_second=10) as live:
            task = progress.add_task("Measuring impedance", total=electrode_count)

            # If we are verbose, we want to show the latest log
            stop_tailing_logs = asyncio.Event()

            def update_progress():
                while not stop_tailing_logs.is_set():
                    if self.new_log_event.is_set():
                        live.update(get_renderable())
                        self.new_log_event.clear()

            progress_thread = None
            if self.verbose:
                progress_thread = Thread(target=update_progress, daemon=True)
                progress_thread.start()

            for response in self.device.stream_query(request):
                if not response:
                    self.console.log("Stream is complete")
                    break

                # Check if this failed
                if response.code != 0 or not response.impedance:
                    failed_batch = response.impedance.measurements
                    failed_measurements.extend(failed_batch)

                    failed_ids = [m.electrode_id for m in failed_batch]
                    progress.console.log(
                        f"Failed to measure impedance for {failed_ids}, why: {response.message}"
                    )
                    for sample in failed_batch:
                        progress.console.log(
                            f"electrode id (mag, phase): {sample.electrode_id}\t {sample.magnitude},{sample.phase}"
                        )
                    measurements_received += len(failed_batch)
                    progress.update(
                        task, completed=min(measurements_received, electrode_count)
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
                self.save_measurement_batch(filename, measurement_batch)

                if self.verbose:
                    for measurement in measurement_batch:
                        progress.console.log(
                            f"Electrode {measurement.electrode_id}: {measurement.magnitude}Ω"
                        )

            if progress_thread:
                stop_tailing_logs.set()
                progress_thread.join()

        if all_measurements:
            self.display_impedance_results(all_measurements)
        else:
            self.console.log("[bold red] All impedance measurements failed")

        if failed_measurements:
            failed_ids = [m.electrode_id for m in failed_measurements]
            self.console.log(f"[bold red]Failed impedance electrodes\n{failed_ids}")
        return True

    def display_impedance_results(self, measurements):
        table = Table(title="Impedance Measurements")
        table.add_column("Electorde ID", justify="right")
        table.add_column("Magnitude (kΩ)", justify="right")
        table.add_column("Phase (°)", justify="right")

        for measurement in measurements:
            table.add_row(
                str(measurement.electrode_id),
                f"{measurement.magnitude:.2f}",
                f"{measurement.phase:.2f}",
            )
        self.console.print(table)

    def save_measurement_batch(self, filename, measurements):
        # Save a batch of measurements as they come in
        with open(filename, "a", newline="") as f:
            writer = csv.writer(f)
            for measurement in measurements:
                writer.writerow(
                    [measurement.electrode_id, measurement.magnitude, measurement.phase]
                )


def load_config_from_file(path_to_config):
    try:
        with open(path_to_config, "r") as f:
            data = f.read()
            proto = Parse(data, QueryRequest())
            return proto
    except Exception:
        print(f"Failed to open {path_to_config}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stream Query Client Test")
    parser.add_argument("--uri", default="localhost:50051", help="Synapse server URI")
    parser.add_argument("--verbose", action="store_true", help="Use verbose output")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to the QueryRequest configuration, in JSON format",
        required=True,
    )

    args = parser.parse_args()

    config_path = args.config
    request_config = load_config_from_file(config_path)
    if not request_config:
        sys.exit(1)

    client = StreamingQueryClient(args.uri, args.verbose)
    request = StreamQueryRequest(request=request_config)

    try:
        if not client.stream_query(request):
            print("Failed to stream query for device")
            sys.exit(1)
    except Exception as e:
        print(f"Failed to stream query. Why: {e}")
        sys.exit(1)
