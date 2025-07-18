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

    def save_channel_to_csv(self, channel_id: int, filename: str) -> bool:
        """Save a specific channel's data (timestamp, sample) to CSV"""
        try:
            # Get the index of the channel_id in channel_ids list
            channel_index = self.channel_ids.index(channel_id)

            # Get timestamp and sample data
            timestamps = self.time_array
            samples = self.data.iloc[:, channel_index].to_numpy()

            # Create DataFrame for export
            export_df = pd.DataFrame(
                {"timestamp_s": timestamps, "sample_value": samples}
            )

            # Save to CSV
            export_df.to_csv(filename, index=False)
            return True

        except (ValueError, Exception):
            return False


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

        timestamps_ns = f["/acquisition/timestamp_ns"]
        total_duration = timestamps_ns[-1] - timestamps_ns[0]
        console.print(f"Total duration: {total_duration / 1e9:.2f} seconds")

        sequence_number = f["/acquisition/sequence_number"]

        # Check for gaps in sequence numbers with progress bar
        gaps_found = []

        with Progress(console=console) as progress:
            task = progress.add_task(
                "Checking sequence numbers...", total=len(sequence_number)
            )

            # Convert to numpy array for faster processing
            seq_array = sequence_number[:]

            # Start with the first sequence number as the expected value
            expected_sequence = seq_array[0]

            for i in range(len(seq_array)):
                current_seq = seq_array[i]
                if current_seq != expected_sequence:
                    gaps_found.append(
                        {
                            "index": i,
                            "expected": expected_sequence,
                            "actual": current_seq,
                            "gap_size": current_seq - expected_sequence,
                        }
                    )
                expected_sequence = current_seq + 1
                progress.update(task, advance=1)

        if gaps_found:
            console.print(
                f"[red]⚠️  Found {len(gaps_found)} gaps in sequence numbers:[/red]"
            )
            for gap in gaps_found:
                gap_in_seconds = gap["gap_size"] / sample_rate
                console.print(
                    f"[red]  Index {gap['index']}: Expected {gap['expected']}, got {gap['actual']} (gap of {gap_in_seconds:.2f}s)[/red]"
                )
        else:
            console.print(
                f"[green]✓ Sequence numbers are continuous ({seq_array[0]} to {seq_array[-1]})[/green]"
            )

        # Print first few and last few sequence numbers for reference
        if len(seq_array) > 10:
            console.print(f"First 5 sequence numbers: {seq_array[:5].tolist()}")
            console.print(f"Last 5 sequence numbers: {seq_array[-5:].tolist()}")
        else:
            console.print(f"All sequence numbers: {seq_array[:].tolist()}")

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
    initial_data = plot_data.data.iloc[:, 0].to_numpy()
    initial_data_centered = initial_data - np.mean(initial_data)
    curve_single = plot_single.plot(
        time_arr,
        initial_data_centered,
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
        channel_data = plot_data.data.iloc[:, channel_index].to_numpy()
        channel_data_centered = channel_data - np.mean(channel_data)
        curve_single.setData(time_arr, channel_data_centered)
        curve_single.setPen(pg.intColor(channel_index, hues=plot_data.num_channels))

        # Update FFT plot
        fft_plot.clear()
        fft_freq, fft_magnitude = compute_fft(
            channel_data_centered, plot_data.sample_rate
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

    # Function to save current channel to CSV
    def save_channel_csv():
        current_channel_id = int(combo.currentText())

        # Open file dialog
        options = QtWidgets.QFileDialog.Options()
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            main_widget,
            f"Save Channel {current_channel_id} Data",
            f"channel_{current_channel_id}_data.csv",
            "CSV Files (*.csv);;All Files (*)",
            options=options,
        )

        if filename:
            success = plot_data.save_channel_to_csv(current_channel_id, filename)
            if success:
                console.print(
                    f"[green]✓ Channel {current_channel_id} data saved to {filename}[/green]"
                )
                # Show success message in GUI
                msg = QtWidgets.QMessageBox()
                msg.setIcon(QtWidgets.QMessageBox.Information)
                msg.setWindowTitle("Export Successful")
                msg.setText(
                    f"Channel {current_channel_id} data successfully saved to:\n{filename}"
                )
                msg.exec_()
            else:
                console.print(
                    f"[red]✗ Failed to save channel {current_channel_id} data[/red]"
                )
                # Show error message in GUI
                msg = QtWidgets.QMessageBox()
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setWindowTitle("Export Failed")
                msg.setText(f"Failed to save channel {current_channel_id} data")
                msg.exec_()

    # Create save button
    save_button = QtWidgets.QPushButton("Save Channel to CSV")
    save_button.clicked.connect(save_channel_csv)
    save_button.setFixedWidth(150)

    # Create a horizontal layout for controls
    controls_layout = QtWidgets.QHBoxLayout()
    controls_layout.addWidget(QtWidgets.QLabel("Channel:"))
    controls_layout.addWidget(combo)
    controls_layout.addWidget(save_button)
    controls_layout.addStretch()  # Add stretch to push everything to the left

    controls_widget = QtWidgets.QWidget()
    controls_widget.setLayout(controls_layout)

    # Create a layout for our plot, fft, and controls
    main_layout = QtWidgets.QVBoxLayout()
    main_layout.addWidget(controls_widget)
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
