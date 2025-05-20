#! /usr/bin/env python3
import argparse
import queue
from threading import Thread, Event

from synapse.client.taps import Tap
from synapse.api.datatype_pb2 import BroadbandFrame
from synapse.cli.synapse_plotter import plot_synapse_data


def main():
    parser = argparse.ArgumentParser(
        description="Stream and plot broadband data from a Synapse device"
    )
    parser.add_argument(
        "--uri",
        type=str,
        required=True,
        help="The URI of the Synapse device (e.g., 'tcp://localhost:5555')",
    )
    parser.add_argument(
        "--tap-point",
        type=str,
        default="broadband_source_1",
        help="Name of the tap point for broadband data",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose output from tap client"
    )
    parser.add_argument(
        "--window-size",
        type=float,
        default=5.0,
        help="Plot window size in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--signal-separation",
        type=int,
        default=1000,
        help="Vertical separation offset for selected channels (default: 1000)",
    )
    parser.add_argument(
        "--default-channels",
        type=str,
        default="",
        help="Comma-separated list of initial channel indices to plot (e.g., '0,1,2,3,4'). Defaults to first 5.",
    )

    args = parser.parse_args()

    print(f"Connecting to Synapse device at {args.uri}, tap point {args.tap_point}...")
    tap = Tap(args.uri, args.verbose)
    try:
        if not tap.connect(args.tap_point):
            print(
                f"Error: Could not connect to tap point '{args.tap_point}'. Check URI and tap name. List available taps if unsure."
            )
            return
    except Exception as e:
        print(
            f"Error connecting to tap '{args.tap_point}' at '{args.uri}': {e}. Exiting."
        )
        return
    print("Connected.")

    print(
        "Waiting for the first data frame to determine channel count and sample rate..."
    )
    first_message_content = None
    try:
        first_message_content = tap.read(timeout_ms=5000)
    except Exception as e:
        print(f"Error reading first message from tap: {e}")
        tap.disconnect()
        return

    if not first_message_content:
        print("Error: No data received from tap after 5 seconds (timeout). Exiting.")
        tap.disconnect()
        return

    first_frame = BroadbandFrame()
    try:
        first_frame.ParseFromString(first_message_content)
    except Exception as e:
        print(f"Error parsing first frame: {e}. Exiting.")
        tap.disconnect()
        return

    num_channels = len(first_frame.frame_data)
    sample_rate_hz = (
        first_frame.sample_rate_hz
        if hasattr(first_frame, "sample_rate_hz") and first_frame.sample_rate_hz > 0
        else 0
    )

    if num_channels == 0:
        print(
            "Error: First frame contains no channel data (num_channels=0). Plotter cannot initialize. Exiting."
        )
        tap.disconnect()
        return
    if sample_rate_hz == 0:
        print(
            "Error: Sample rate reported as 0 Hz or missing in the first frame. Plotter cannot initialize. Exiting."
        )
        tap.disconnect()
        return

    print(f"Initialized: {num_channels} channels, Sample Rate: {sample_rate_hz} Hz.")

    # Select which channels to plot
    channel_ids_to_plot = []
    if args.default_channels:
        try:
            indices = [int(x.strip()) for x in args.default_channels.split(",")]
            channel_ids_to_plot = [i for i in indices if 0 <= i < num_channels]
            if len(channel_ids_to_plot) != len(indices):
                print(
                    f"Warning: Some selected channel indices were invalid. Using valid ones: {channel_ids_to_plot}"
                )
        except ValueError:
            print(
                f"Warning: Could not parse --default-channels '{args.default_channels}'. Using default channels."
            )
            channel_ids_to_plot = list(range(min(5, num_channels)))
    else:
        channel_ids_to_plot = list(range(num_channels))

    print(f"Plotting channels: {channel_ids_to_plot}")

    # Add more detailed debug info about the channels
    print(f"Selected channels for plotting: {channel_ids_to_plot}")
    print("Using these as channel IDs in the SynapsePlotter")

    # The original SynapsePlotter expects channel IDs, not just indices
    # For our BroadbandFrame data, the indices are the IDs
    # Make channel IDs explicitly match the indices to avoid confusion
    channel_indices = channel_ids_to_plot

    # Setup communication between the tap reader thread and plotter thread
    data_queue = queue.Queue(maxsize=max(sample_rate_hz * 2, 100))
    stop_event = Event()

    # Create a data adapter class to translate between BroadbandFrame and the format expected by SynapsePlotter
    class BroadbandFrameAdapter:
        def __init__(self, channel_id, sample_data, timestamp_ns, sequence_number):
            self.channel_id = channel_id
            self.samples = [(channel_id, sample_data)]
            self.timestamp_ns = timestamp_ns
            self.sequence_number = sequence_number

    # Start plotter in a separate thread
    plotter_thread = Thread(
        target=plot_synapse_data,
        args=(
            stop_event,
            data_queue,
            int(sample_rate_hz),
            int(args.window_size),
            channel_indices,
        ),
        daemon=True,
    )
    plotter_thread.start()

    # Process the first frame
    if len(first_frame.frame_data) > 0:
        for channel_idx in channel_ids_to_plot:
            if 0 <= channel_idx < len(first_frame.frame_data):
                # In the adapter, use the channel index as the channel ID
                # This works because in the original SynapsePlotter, it expects a dict mapping from channel ID to index
                channel_value = float(first_frame.frame_data[channel_idx])
                adapter = BroadbandFrameAdapter(
                    channel_idx,
                    [channel_value],
                    first_frame.timestamp_ns,
                    first_frame.sequence_number,
                )
                try:
                    data_queue.put_nowait(adapter)
                except queue.Full:
                    pass  # Ignore if queue is full for first sample

    print("Streaming data... Press Ctrl+C to stop.")
    frames_processed = 1
    last_frame_sequence_number = first_frame.sequence_number

    try:
        log_interval_frames = max(
            sample_rate_hz // 10, 100
        )  # Log every ~0.1 seconds of data

        while not stop_event.is_set() and plotter_thread.is_alive():
            message = tap.read(timeout_ms=100)
            if message is None:
                if not stop_event.is_set() and plotter_thread.is_alive():
                    if tap.zmq_socket is None:
                        print(
                            "Tap connection appears to be lost (socket is None). Stopping data reading."
                        )
                        break
                    continue
                else:
                    break

            broadband_frame = BroadbandFrame()
            try:
                broadband_frame.ParseFromString(message)
            except Exception as e:
                print(f"Error parsing broadband frame: {e}. Skipping.")
                continue

            if broadband_frame.sequence_number < last_frame_sequence_number:
                print(
                    f"Warning: Out of order frame received. Expected sequence number {last_frame_sequence_number}, got {broadband_frame.sequence_number}. Ignoring frame."
                )
                continue

            last_frame_sequence_number = broadband_frame.sequence_number

            if len(broadband_frame.frame_data) != num_channels:
                print(
                    f"Warning: Inconsistent frame data length received. Expected {num_channels}, got {len(broadband_frame.frame_data)}. Ignoring frame."
                )
                continue

            # Convert and queue frame data for each tracked channel
            for channel_idx in channel_ids_to_plot:
                if 0 <= channel_idx < len(broadband_frame.frame_data):
                    channel_value = float(broadband_frame.frame_data[channel_idx])
                    adapter = BroadbandFrameAdapter(
                        channel_idx,
                        [channel_value],
                        broadband_frame.timestamp_ns,
                        broadband_frame.sequence_number,
                    )
                    try:
                        data_queue.put_nowait(adapter)
                    except queue.Full:
                        # Queue is full, just skip this sample
                        pass

            frames_processed += 1
            if frames_processed % log_interval_frames == 0:
                print(
                    f"Processed {frames_processed} frames. Sequence: {broadband_frame.sequence_number}"
                )

    except KeyboardInterrupt:
        print("\nCtrl+C received. Initiating shutdown...")
    except Exception as e:
        print(f"An error occurred in the main data reading loop: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print("Signalling plotter to stop...")
        stop_event.set()

        print("Disconnecting tap...")
        if hasattr(tap, "disconnect"):
            tap.disconnect()

        if plotter_thread.is_alive():
            print("Waiting for plotter thread to finish (max 5s)...")
            plotter_thread.join(timeout=5)
            if plotter_thread.is_alive():
                print("Warning: Plotter thread did not exit cleanly.")
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
