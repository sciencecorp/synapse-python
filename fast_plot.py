#!/usr/bin/env python3
import argparse
import sys
import os
import json
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


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
def compute_fft(data, sample_rate):
    fft_values = np.fft.fft(data)
    fft_freq = np.fft.fftfreq(len(data), d=1 / sample_rate)
    fft_values = np.abs(fft_values)[: len(fft_values) // 2]
    fft_freq = fft_freq[: len(fft_freq) // 2]
    fft_values /= max(fft_values)
    fft_values[1:] *= 2
    fft_values[0] = 0
    return fft_freq, fft_values


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Plot Synapse Data Recording")
    parser.add_argument(
        "fname", type=str, help="Path to the binary data file", required=True
    )
    parser.add_argument(
        "config_json",
        type=str,
        help="Path to the configuration JSON file used for the recording",
        required=True,
    )

    # Optionally, allow for a time range to be specified
    parser.add_argument(
        "--time",
        type=str,
        help="Time range to plot in seconds",
        required=False,
        default=None,
    )
    parser.add_argument(
        "--channels",
        type=str,
        help='Channels to plot, comma separated (e.g. "1,2,3")',
        required=False,
        default=None,
    )
    args = parser.parse_args()

    # Start with loading the config
    sampling_freq, num_channels, channel_ids = load_config(args.config_json)
    logger.info(f"Loaded config with {num_channels} channels: {channel_ids}")


#     # Load the data
#     data = process_data(args.fname, num_channels)


#     # GUI Initialization
#     app = QtWidgets.QApplication(sys.argv)
#     win = pg.GraphicsLayoutWidget(title=f"Synapse Data Recording - ")
#     win.resize(1280, 720)
#     win.show()

# # Create the main plot
# plot = win.addPlot(title="All Channels")
# plot.setLabel('bottom', 'Time (s)')
# plot.setLabel('left', 'Amplitude')
# plot.addLegend()
# plot.showGrid(x=True, y=True)

# # Create FFT Subwindow
# fft_win = pg.GraphicsLayoutWidget(title="FFT of Selected Channel")
# fft_win.resize(600, 400)
# fft_plot = fft_win.addPlot(title="FFT Analysis")
# fft_plot.setLabel('bottom', 'Frequency (Hz)')
# fft_plot.setLabel('left', 'Amplitude')
# fft_plot.showGrid(x=True, y=True)
# fft_win.show()

# # Load command-line arguments
# fname = sys.argv[1]
# config_json = sys.argv[2]

# # Load config & data
# sampling_freq, num_channels, channel_ids = load_config(config_json)
# data = process_data(fname, num_channels)

# # Time vector
# n_samples = len(data)
# t = np.arange(n_samples) / sampling_freq

# # Plot data
# curves = []
# offset = 500
# for i, channel_id in enumerate(channel_ids):
#     final_data = data.iloc[:, i] - offset * i
#     curve = plot.plot(t, final_data, pen=pg.intColor(i, hues=num_channels), name=f'Ch {channel_id}')
#     curve.setDownsampling(auto=True)
#     curve.setClipToView(True)
#     curves.append(curve)

# # FFT Update Function
# def update_fft(selected_channel):
#     fft_plot.clear()
#     data_col_index = channel_ids.index(selected_channel)
#     fft_freq, fft_values = compute_fft(data.iloc[:, data_col_index], sampling_freq)
#     fft_plot.plot(fft_freq, fft_values, pen='y', name=f'FFT of Ch {selected_channel}')

# # Dropdown for channel selection
# combo = QtWidgets.QComboBox()
# combo.addItems([str(ch) for ch in channel_ids])
# combo.currentIndexChanged.connect(lambda: update_fft(int(combo.currentText())))
# combo.setFixedWidth(100)

# # Create layout with dropdown
# layout = QtWidgets.QVBoxLayout()
# layout.addWidget(combo)
# layout.addWidget(fft_win)

# # Main Widget
# main_widget = QtWidgets.QWidget()
# main_widget.setLayout(layout)
# main_widget.show()

# Start the Qt event loop
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    # update_fft(channel_ids[0])  # Default to first channel
    # QtWidgets.QApplication.instance().exec()
