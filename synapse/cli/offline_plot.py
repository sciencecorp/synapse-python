import sys
import os
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets
import logging
import signal

BACKGROUND_COLOR = "#253252250"


def add_commands(subparsers):
    a = subparsers.add_parser("plot", help="Plot recorded synapse data")
    a.add_argument("fname", type=str, help="Path to the binary data file")
    a.add_argument(
        "config_json",
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
def process_data(file_path, num_channels):
    _, file_extension = os.path.splitext(file_path)

    if file_extension in [".bin", ".dat"]:
        with open(file_path, "rb") as f:
            data = np.fromfile(f, dtype=np.int16)

        df = pd.DataFrame(data)
        new_len = len(df) // num_channels
        df = df.head(new_len * num_channels)
        df = df.values.reshape(-1, num_channels)

        return pd.DataFrame(df)

    raise ValueError("Unsupported file format. Expected .bin or .dat")


# Load configuration from JSON
def load_config(json_path):
    with open(json_path) as f:
        config = json.load(f)

    nodes = config["nodes"]
    for node in nodes:
        if node["type"] == "kElectricalBroadband":
            recording_config = node["electrical_broadband"]
            sampling_freq = recording_config["sample_rate"]
            num_channels = len(recording_config["channels"])
            channel_ids = [channel["id"] for channel in recording_config["channels"]]
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

    # Start with loading the config
    sampling_freq, num_channels, channel_ids = load_config(args.config_json)
    if args.channels:
        channel_ids = [int(ch) for ch in args.channels.split(",")]
    logger.info(f"Loaded config with {num_channels} channels")

    # Load the data
    data = process_data(args.fname, num_channels)
    logger.info(f"Loaded data with {data.shape[1]} channels")

    # Setup the window for the plot
    pg.setConfigOption("background", BACKGROUND_COLOR)
    win = pg.GraphicsLayoutWidget(title=f"Synapse Data Recording - {args.fname}")
    win.resize(1280, 720)

    # Main plot is all the channels
    plot = win.addPlot(row=0, col=0, title="Channels")
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
        final_data = (
            data.iloc[:, i].to_numpy() - offset * i
        )  # Convert Series to NumPy array

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
    plot_single = win.addPlot(row=1, col=0, title="Single Channel")
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
    fft_plot = win.addPlot(row=0, col=1, rowspan=2, title="FFT of Selected Channel")
    fft_plot.setLabel("bottom", "Frequency (Hz)")
    fft_plot.setLabel("left", "Amplitude")
    fft_plot.showGrid(x=True, y=True)

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
    main_layout.addWidget(win)

    # And finally our main widget to show
    main_widget = QtWidgets.QWidget()
    main_widget.setLayout(main_layout)
    main_widget.show()

    # Handle the case of Ctrl+C (the user might be like me and press this instead of the Exit button)
    def signal_handler(sig, frame):
        logger.info("Ctrl+C pressed. Exiting...")
        QtWidgets.QApplication.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    win.show()
    QtWidgets.QApplication.instance().exec()
