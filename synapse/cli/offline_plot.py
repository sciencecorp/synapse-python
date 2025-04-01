import sys
import struct
import os
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import logging
import signal

BACKGROUND_COLOR = "#253252250"


def add_commands(subparsers):
    a = subparsers.add_parser("plot", help="Plot recorded synapse data")
    a.add_argument("--data", type=str, help="Path to the binary data file")
    a.add_argument(
        "--config",
        type=str,
        help="Path to the configuration JSON file used for the recording",
    )
    a.add_argument(
        "--time",
        type=str,
        help="Time range to plot in seconds. Can be a range: start:end (e.g. 0:10) or a single end time (e.g. 10)",
        required=False,
        default=None,
    )
    a.add_argument(
        "--channels",
        type=str,
        help='Channels to plot, comma separated (e.g. "1,2,3")',
        required=False,
        default=None,
    )
    a.add_argument(
        "--dir", type=str, help="Directory containing the data and config files"
    )
    a.set_defaults(func=plot)


def setup_logging():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


# Function to load binary data produced by the stream recording
def process_data(file_path, num_channels, logger):
    _, file_extension = os.path.splitext(file_path)

    if file_extension in [".bin"]:
        with open(file_path, "rb") as f:
            data = np.fromfile(f, dtype=np.int16)

        df = pd.DataFrame(data)
        new_len = len(df) // num_channels
        df = df.head(new_len * num_channels)
        df = df.values.reshape(-1, num_channels)

        return pd.DataFrame(df)

    if file_extension in [".dat"]:
        with open(file_path, "rb") as f:
            data = np.fromfile(f, dtype=np.int16)

        df = pd.DataFrame(data)
        new_len = (len(df)) // num_channels
        df = df.tail(
            -num_channels
        )  # Remove the header info containing the channel mapping
        df = df.head(new_len * num_channels)
        df = df.values.reshape(-1, num_channels)

        return pd.DataFrame(df)

    if file_extension in [".jsonl"]:
        channel_data = {}

        with open(file_path, "r") as f:
            for line in f:
                try:
                    json_obj = json.loads(line)  # Load JSON object (list)
                    _, channels = json_obj  # Ignore timestamp, extract channel data
                    for ch_id, samples in channels:
                        if ch_id not in channel_data:
                            channel_data[ch_id] = []
                        channel_data[ch_id].extend(samples)

                except (json.JSONDecodeError, ValueError, IndexError) as e:
                    logger.error(
                        f"Warning: Skipping malformed JSON line in {file_path} - {e}"
                    )

        # sort dict by key
        channel_data = dict(sorted(channel_data.items()))

        # Convert lists to numpy arrays
        min_val = min(len(samples) for samples in channel_data.values())

        # Truncate all channels to the length of the shortest channel
        for ch_id, samples in channel_data.items():
            channel_data[ch_id] = np.array(samples[:min_val])

        return pd.DataFrame(channel_data)

    raise ValueError("Unsupported file format. Expected .bin, .dat, or .jsonl")


# Load configuration from JSON
def load_config(json_path):
    with open(json_path) as f:
        config = json.load(f)

    nodes = config["nodes"]
    for node in nodes:
        if node["type"] == "kBroadbandSource":
            recording_config = node.get("broadband_source", None)
            if recording_config is None:
                recording_config = node["broadbandSource"]
            sampling_freq = recording_config.get("sample_rate_hz", None)
            if sampling_freq is None:
                sampling_freq = recording_config["sampleRateHz"]

            electrode_config = recording_config["signal"]["electrode"]
            num_channels = len(electrode_config["channels"])
            channel_ids = [
                channel.get("id", 0) for channel in electrode_config["channels"]
            ]
            return sampling_freq, num_channels, channel_ids

    raise ValueError("Invalid JSON: No 'kElectricalBroadband' node found")


# Function to compute FFT
# NOTE(gilbert): This is the previous implementation of the FFT
# def compute_fft(data, sample_rate):
#     fft_values = np.fft.fft(data)
#     fft_freq = np.fft.fftfreq(len(data), d=1 / sample_rate)
#     fft_values = np.abs(fft_values)[: len(fft_values) // 2]
#     fft_freq = fft_freq[: len(fft_freq) // 2]
#     fft_values /= max(fft_values)
#     fft_values[1:] *= 2
#     fft_values[0] = 0
#     return fft_freq, fft_values


def compute_fft(data, sample_rate):
    # Apply window function to reduce spectral leakage
    window = np.hanning(len(data))
    windowed_data = data * window

    # Compute FFT
    fft_values = np.fft.rfft(windowed_data)  # Using rfft for real input
    fft_freq = np.fft.rfftfreq(len(data), d=1 / sample_rate)

    # Convert to magnitude in dB
    # Add small number to avoid log(0)
    fft_magnitude_db = 20 * np.log10(np.abs(fft_values) + 1e-10)

    return fft_freq, fft_magnitude_db


def plot(args):
    logger = setup_logging()

    app = QtWidgets.QApplication.instance()
    if not app:
        app = QtWidgets.QApplication(sys.argv)

    data_file = None
    config_file = None
    if args.dir:
        # We expect there to be a .dat file and a .json file in the directory
        for file in os.listdir(args.dir):
            if (
                file.endswith(".dat")
                or file.endswith(".bin")
                or file.endswith(".jsonl")
            ):
                data_file = os.path.join(args.dir, file)
            elif file.endswith(".json"):
                config_file = os.path.join(args.dir, file)

    if args.data:
        data_file = args.data
    if args.config:
        config_file = args.config

    # Start with loading the config
    sampling_freq, num_channels, channel_ids = load_config(config_file)
    if args.channels:
        channel_ids = [int(ch) for ch in args.channels.split(",")]
    logger.info(f"Loaded config with {num_channels} channels")

    # Load the data
    data = process_data(data_file, num_channels, logger)
    logger.info(f"Loaded data with {data.shape[1]} channels")

    # Extract channel ids from data file header
    if data_file.endswith(".dat"):
        size = os.path.getsize(data_file)
        if size > num_channels * 2:
            with open(data_file, "rb") as f:
                header = f.read(num_channels * 2)
                channel_ids = struct.unpack("h" * num_channels, header)
        else:
            logger.error(
                f"Data file is too small to contain channel ids. Expected {num_channels} channels."
            )
            return

    # Setup the window for the plot
    pg.setConfigOption("background", BACKGROUND_COLOR)

    # To allow for resizing, we need to add a splitter
    main_splitter = QtWidgets.QSplitter()
    main_splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)

    left_splitter = QtWidgets.QSplitter()
    left_splitter.setOrientation(QtCore.Qt.Orientation.Vertical)

    # Add widgets so we can resize
    time_plot_widget = pg.GraphicsLayoutWidget()
    single_channel_plot_widget = pg.GraphicsLayoutWidget()
    fft_plot_widget = pg.GraphicsLayoutWidget()

    # Main plot is all the channels
    plot = time_plot_widget.addPlot(row=0, col=0, title="Channels")
    plot.setLabel("bottom", "Time (s)")
    plot.setLabel("left", "Amplitude (counts)")
    plot.addLegend()
    plot.showGrid(x=True, y=True)

    # Create a list to hold the curves
    curves = []

    # Offset in counts for each channel
    offset = 500

    # Create time array since we are getting the data in samples, not time
    start_time, end_time = 0, None
    if args.time:
        try:
            time_parts = args.time.split(":")
            if len(time_parts) == 1:
                end_time = float(time_parts[0])
            elif len(time_parts) == 2:
                start_time = float(time_parts[0])
                end_time = float(time_parts[1])
            else:
                raise ValueError(
                    "Invalid time range format. Expected: start:end or end"
                )
            logger.info(f"Plotting data from {start_time} to {end_time} seconds")
        except ValueError as e:
            logger.error(f"Error parsing time range: {e}")
            sys.exit(1)

    full_time_arr = np.arange(len(data)) / sampling_freq
    if end_time is not None:  # FIX: Ensure end_time=0 is valid
        mask = (full_time_arr >= start_time) & (full_time_arr <= end_time)

        if np.any(mask):  # FIX: Ensure non-empty selection
            data = data.loc[mask]  # FIX: Use .loc instead of .iloc
            time_arr = full_time_arr[mask]
            logger.info(
                f"Plotting {len(data)} samples from {time_arr[0]:.2f}s to {time_arr[-1]:.2f}s"
            )
        else:
            logger.warning("Time range resulted in no data points. Plotting all data.")
            time_arr = full_time_arr
    else:
        time_arr = full_time_arr
        logger.info(
            f"Plotting all {len(data)} samples (~{len(data) / sampling_freq:.2f} seconds)"
        )

    # Create a curve for each channel
    for i, channel_id in enumerate(channel_ids):
        final_data = data.iloc[:, i].to_numpy().astype(np.float32) - offset * i

        if len(time_arr) != len(final_data):
            logger.error(
                f"Mismatch in time and data length. Skipping channel {channel_id}."
            )
            continue

        curve = plot.plot(
            time_arr,
            final_data,
            pen=pg.intColor(i, hues=num_channels),
            name=f"Ch {channel_id}",
        )
        curve.setDownsampling(auto=True)
        curve.setClipToView(True)
        curves.append(curve)

    # Create a single plot for a single channel
    plot_single = single_channel_plot_widget.addPlot(
        row=1, col=0, title="Single Channel"
    )
    plot_single.setLabel("bottom", "Time (s)")
    plot_single.setLabel("left", "Amplitude (counts)")
    plot_single.showGrid(x=True, y=True)

    # Create a curve for the single channel
    curve_single = plot_single.plot(
        time_arr,
        data.iloc[:, 0].to_numpy(),
        pen=pg.intColor(channel_ids[0], hues=num_channels),
        name=f"Ch {channel_ids[0]}",
    )
    curve_single.setDownsampling(auto=True)
    curve_single.setClipToView(True)
    curves.append(curve_single)

    # Create an fft plot of the selected channel
    fft_plot = fft_plot_widget.addPlot(
        row=0, col=1, rowspan=2, title="FFT of Selected Channel"
    )
    fft_plot.setLabel("bottom", "Frequency (Hz)")
    fft_plot.setLabel("left", "Amplitude")
    fft_plot.showGrid(x=True, y=True)

    # Splotters for the widgets
    left_splitter.addWidget(time_plot_widget)
    left_splitter.addWidget(single_channel_plot_widget)
    main_splitter.addWidget(left_splitter)
    main_splitter.addWidget(fft_plot_widget)

    # Log scale for frequency axis
    fft_plot.setLogMode(x=True, y=False)

    # Enable auto-range on double click
    fft_plot.autoBtn.clicked.connect(lambda: fft_plot.enableAutoRange())

    # Create a curve for the fft of the selected channel
    curve_fft = fft_plot.plot(
        data.iloc[:, 0].to_numpy(),
        pen=pg.intColor(0, hues=num_channels),
        name=f"FFT of Ch {channel_ids[0]}",
    )
    curve_fft.setClipToView(True)

    # Allow the user to select a single channel
    def update_single_channel(channel_id):
        # Get the index of the channel_id in channel_ids list
        channel_index = channel_ids.index(int(channel_id))

        # Update time domain plot
        curve_single.setData(time_arr, data.iloc[:, channel_index].to_numpy())
        curve_single.setPen(pg.intColor(channel_index, hues=num_channels))

        # Update FFT plot
        fft_plot.clear()
        fft_freq, fft_magnitude = compute_fft(
            data.iloc[:, channel_index].to_numpy(), sampling_freq
        )

        # Plot FFT with improved visibility
        curve_fft = fft_plot.plot(
            fft_freq,
            fft_magnitude,
            pen=dict(color="w", width=2),
            name=f"FFT of Ch {channel_id}",
        )
        # Note(gilbert): Downsampling the FFT doesn't seem like the correct way to do this
        curve_fft.setClipToView(True)

        # Add grid lines
        fft_plot.showGrid(x=True, y=True, alpha=0.3)

        # Auto-range on channel change
        fft_plot.autoRange()

    update_single_channel(channel_ids[0])

    # Create a dropdown for channel selection
    combo = QtWidgets.QComboBox()
    combo.addItems([str(ch) for ch in channel_ids])
    combo.currentIndexChanged.connect(
        lambda: update_single_channel(int(combo.currentText()))
    )
    combo.setFixedWidth(100)

    # Create a layout for our plot, fft, and controls
    main_layout = QtWidgets.QVBoxLayout()
    main_layout.addWidget(combo)

    main_layout.addWidget(main_splitter)

    # And finally our main widget to show
    main_widget = QtWidgets.QWidget()
    main_widget.setLayout(main_layout)
    main_widget.setWindowTitle(
        f"Synapse Data Recording - {data_file}"
    )  # Add window title here
    main_widget.resize(1280, 720)  # Add resize here
    main_widget.show()

    # Handle the case of Ctrl+C (the user might be like me and press this instead of the Exit button)
    def signal_handler(sig, frame):
        logger.info("Ctrl+C pressed. Exiting...")
        QtWidgets.QApplication.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    app.exec()
