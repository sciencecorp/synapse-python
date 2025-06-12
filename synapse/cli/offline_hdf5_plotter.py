#!/usr/bin/env python3

import sys
import signal
import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
from dataclasses import dataclass
from typing import List
import time
import h5py
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

BACKGROUND_COLOR = "#253252250"


@dataclass
class PlotData:
    data: pd.DataFrame  # DataFrame with samples x channels
    sample_rate: float
    channel_ids: List[int]

    @property
    def num_samples(self) -> int:
        return len(self.data)

    @property
    def num_channels(self) -> int:
        return len(self.data.columns)

    @property
    def duration_seconds(self) -> float:
        return self.num_samples / self.sample_rate

    @property
    def time_array(self) -> np.ndarray:
        return np.arange(self.num_samples) / self.sample_rate

    def filter_channels(self, channel_ids: List[int]) -> "PlotData":
        # They come in as a list of strings delimited by commas
        channel_ids = [int(ch) for ch in channel_ids.split(",")]
        return PlotData(
            data=self.data.loc[:, channel_ids],
            sample_rate=self.sample_rate,
            channel_ids=channel_ids,
        )


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


def print_tree(group, console, prefix=""):
    """Print group tree with attributes"""
    items = list(group.items())
    for i, (name, obj) in enumerate(items):
        is_last = i == len(items) - 1
        current_prefix = "└── " if is_last else "├── "

        if isinstance(obj, h5py.Group):
            console.print(f"{prefix}{current_prefix}📁 [blue]{name}/[/blue]")
            # Show group attributes if any
            if obj.attrs:
                for attr_key, attr_val in obj.attrs.items():
                    attr_prefix = prefix + ("    " if is_last else "│   ")
                    console.print(f"{attr_prefix}  @{attr_key}: {attr_val}")
            # Recurse into subgroups
            next_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(obj, console, next_prefix)

        elif isinstance(obj, h5py.Dataset):
            info = f"shape={obj.shape}, dtype={obj.dtype}"
            console.print(f"{prefix}{current_prefix}📄 [green]{name}[/green] ({info})")


def load_h5_data(data_file, console, time_range=None):
    """Load HDF5 data and return PlotData object"""
    console.print(f"Loading h5 data from {data_file}")
    with h5py.File(data_file, "r") as f:
        # Display file info
        attributes = f.attrs
        if attributes:
            table = Table(title="Attributes")
            table.add_column("Key")
            table.add_column("Value")
            for key, value in attributes.items():
                table.add_row(key, str(value))
            console.print(table)

        # List immediate groups (top-level only)
        print_tree(f, console)

        # Get channel information
        channels = f["/general/extracellular_ephys/electrodes/"]
        channel_ids = channels["id"][:].tolist()
        number_of_channels = len(channel_ids)

        sample_rate = float(attributes["sample_rate_hz"])
        console.print(f"Sample rate: {sample_rate} Hz")
        console.print(f"Found {number_of_channels} channels")

        # Get frame data info
        frame_data = f["/acquisition/ElectricalSeries"]
        total_samples = len(frame_data)
        samples_per_channel = total_samples // number_of_channels

        console.print(
            f"Total duration: {samples_per_channel / sample_rate:.2f} seconds"
        )

        # Determine time range to load
        start_index = 0
        end_index = total_samples

        if time_range:
            if ":" in time_range:
                start_time, end_time = map(float, time_range.split(":"))
            else:
                start_time, end_time = 0, float(time_range)

            start_index = int(start_time * sample_rate * number_of_channels)
            end_index = int(end_time * sample_rate * number_of_channels)
            console.print(f"Loading time range {start_time}s to {end_time}s")
        else:
            # Default: load first 10 seconds
            console.print("[yellow]Loading first 10 seconds[/yellow]")
            end_index = min(int(10 * sample_rate * number_of_channels), total_samples)

        # Load data subset
        with console.status("Loading data...", spinner="dots"):
            subset_length = end_index - start_index
            actual_samples_per_channel = subset_length // number_of_channels

            data_slice = frame_data[
                start_index : start_index
                + (actual_samples_per_channel * number_of_channels)
            ]
            reshaped_data = data_slice.reshape(
                actual_samples_per_channel, number_of_channels
            )

            # Create DataFrame
            df = pd.DataFrame(reshaped_data, columns=range(number_of_channels))

        return PlotData(data=df, sample_rate=sample_rate, channel_ids=channel_ids)


def plot(plot_data, console):
    """Create the plotting GUI for HDF5 data"""
    app = QtWidgets.QApplication.instance()
    if not app:
        app = QtWidgets.QApplication(sys.argv)

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
    plot_all = time_plot_widget.addPlot(row=0, col=0, title="All Channels")
    plot_all.setLabel("bottom", "Time (s)")
    plot_all.setLabel("left", "Amplitude (counts)")
    plot_all.addLegend()
    plot_all.showGrid(x=True, y=True)

    # Create a list to hold the curves
    curves = []

    # Offset in counts for each channel
    offset = 500

    # Create time array
    time_arr = plot_data.time_array

    # Create a curve for each channel
    if len(plot_data.channel_ids) > 32:
        console.print(
            "[yellow] Creating curves for large datasets might take a while [/yellow]"
        )
        console.print(
            "[yellow] Consider using the --channels flag to limit the number of channels [/yellow]"
        )
    start_time = time.time()
    with Progress(console=console) as progress:
        task = progress.add_task("Creating curves...", total=len(plot_data.channel_ids))

        for i, channel_id in enumerate(plot_data.channel_ids):
            if i >= plot_data.num_channels:
                break

            final_data = (
                plot_data.data.iloc[:, i].to_numpy().astype(np.float32) - offset * i
            )

            curve = plot_all.plot(
                time_arr,
                final_data,
                pen=pg.intColor(i, hues=plot_data.num_channels),
                name=f"Ch {channel_id}",
            )
            curve.setDownsampling(auto=True)
            curve.setClipToView(True)
            curves.append(curve)

            progress.update(task, advance=1)
    end_time = time.time()
    total_samples = plot_data.num_samples * plot_data.num_channels
    console.print(
        f"Plotted {plot_data.num_channels} channels ({total_samples:,} total samples) in {end_time - start_time:.2f} seconds"
    )
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
        plot_data.data.iloc[:, 0].to_numpy(),
        pen=pg.intColor(0, hues=plot_data.num_channels),
        name=f"Ch {plot_data.channel_ids[0]}",
    )
    curve_single.setDownsampling(auto=True)
    curve_single.setClipToView(True)

    # Create an fft plot of the selected channel
    fft_plot = fft_plot_widget.addPlot(
        row=0, col=1, rowspan=2, title="FFT of Selected Channel"
    )
    fft_plot.setLabel("bottom", "Frequency (Hz)")
    fft_plot.setLabel("left", "Amplitude (dB)")
    fft_plot.showGrid(x=True, y=True)

    # Splitters for the widgets
    left_splitter.addWidget(time_plot_widget)
    left_splitter.addWidget(single_channel_plot_widget)
    main_splitter.addWidget(left_splitter)
    main_splitter.addWidget(fft_plot_widget)

    # Log scale for frequency axis
    fft_plot.setLogMode(x=True, y=False)

    # Enable auto-range on double click
    fft_plot.autoBtn.clicked.connect(lambda: fft_plot.enableAutoRange())

    # Function to update single channel display
    def update_single_channel(channel_id):
        # Get the index of the channel_id in channel_ids list
        try:
            channel_index = plot_data.channel_ids.index(int(channel_id))
        except ValueError:
            return

        # Update time domain plot
        curve_single.setData(time_arr, plot_data.data.iloc[:, channel_index].to_numpy())
        curve_single.setPen(pg.intColor(channel_index, hues=plot_data.num_channels))

        # Update FFT plot
        fft_plot.clear()
        fft_freq, fft_magnitude = compute_fft(
            plot_data.data.iloc[:, channel_index].to_numpy(), plot_data.sample_rate
        )

        # Plot FFT with improved visibility
        curve_fft = fft_plot.plot(
            fft_freq,
            fft_magnitude,
            pen=dict(color="w", width=2),
            name=f"FFT of Ch {channel_id}",
        )
        curve_fft.setClipToView(True)

        # Add grid lines
        fft_plot.showGrid(x=True, y=True, alpha=0.3)

        # Auto-range on channel change
        fft_plot.autoRange()

    # Initialize with first channel
    update_single_channel(plot_data.channel_ids[0])

    # Create a dropdown for channel selection
    combo = QtWidgets.QComboBox()
    combo.addItems([str(ch) for ch in plot_data.channel_ids])
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
    main_widget.setWindowTitle("Synapsectl Data Viewer")
    main_widget.resize(1280, 720)
    main_widget.show()

    # Handle the case of Ctrl+C
    def signal_handler(sig, frame):
        print("Ctrl+C pressed. Exiting...")
        QtWidgets.QApplication.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    app.exec()


def plot_h5(args):
    """Main entry point for HDF5 plotting"""
    console = Console()

    # Load the data
    plot_data = load_h5_data(args.data, console, args.time)

    if plot_data is None:
        console.print("[red]Failed to load data[/red]")
        return

    console.print(
        f"[green]Loaded {plot_data.num_samples:,} samples from {plot_data.num_channels} channels[/green]"
    )
    console.print(f"[green]Duration: {plot_data.duration_seconds:.2f} seconds[/green]")

    # If the user has requested specific channels, filter the data
    if args.channels:
        plot_data = plot_data.filter_channels(args.channels)

    # Create the plot
    plot(plot_data, console)
