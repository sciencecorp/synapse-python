#!/usr/bin/env python3
"""
High-performance neural data visualization using raster/sweep display
Much faster than scrolling plots - similar to oscilloscope displays
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
import threading
from collections import deque
from synapse.client.taps import Tap
from synapse.api.datatype_pb2 import BroadbandFrame as BroadbandFrameProto

# Assuming you have your protobuf compiled
# from your_proto_pb2 import BroadbandFrame


class NeuralRasterDisplay(QtWidgets.QWidget):
    """Fast raster-style display for neural data"""

    def __init__(self, n_channels=5, sample_rate=32000, display_seconds=5):
        super().__init__()

        self.n_channels = n_channels
        self.sample_rate = sample_rate
        self.display_seconds = display_seconds

        # Display parameters
        self.width = 1200  # pixels
        self.height = 800  # pixels
        self.channel_height = self.height // n_channels

        # Calculate downsampling
        total_samples = sample_rate * display_seconds  # 160,000
        self.downsample = total_samples // self.width  # ~133 samples per pixel
        self.samples_per_pixel = self.downsample

        # Data buffer for incoming samples - larger buffer to prevent overflow
        buffer_size = self.downsample * n_channels * 5  # 5x larger buffer
        self.data_buffer = deque(maxlen=buffer_size)

        # Image array for display (channels x width) - black background
        self.image_data = np.zeros((self.height, self.width), dtype=np.float32)

        # Current write position
        self.write_pos = 0

        # Debug counter
        self.pixels_written = 0

        print(
            f"Setup: {n_channels} channels, {self.downsample} samples/pixel, buffer size: {buffer_size}"
        )

        # Setup UI
        self.setup_ui()

        # Update timer - only update the sweep line
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.start(16)  # 60 FPS

        self.setWindowTitle("Neural Data Raster Display")
        self.resize(self.width + 100, self.height + 100)

    def setup_ui(self):
        """Create the display widget"""
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Graphics widget
        self.graphics_widget = pg.GraphicsLayoutWidget()
        layout.addWidget(self.graphics_widget)

        # Single plot with image item
        self.plot = self.graphics_widget.addPlot()
        self.plot.setLabel("left", "Channel")
        self.plot.setLabel("bottom", "Time", units="s")

        # Image item for raster display
        self.img_item = pg.ImageItem()
        self.plot.addItem(self.img_item)

        # Set image dimensions
        self.img_item.setImage(self.image_data)  # No transpose needed

        # Sweep line
        self.sweep_line = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen("r", width=2))
        self.plot.addItem(self.sweep_line)

        # Channel divider lines and baselines
        for i in range(1, self.n_channels):
            y = i * self.channel_height
            line = pg.InfiniteLine(
                pos=y,
                angle=0,
                pen=pg.mkPen("w", width=1, style=QtCore.Qt.PenStyle.DashLine),
            )
            self.plot.addItem(line)

        # Add baseline (center) line for each channel
        for i in range(self.n_channels):
            y = i * self.channel_height + self.channel_height // 2
            baseline = pg.InfiniteLine(
                pos=y,
                angle=0,
                pen=pg.mkPen("gray", width=1, style=QtCore.Qt.PenStyle.DotLine),
            )
            self.plot.addItem(baseline)

        # Channel labels - adjusted for inverted Y
        self.plot.getAxis("left").setTicks(
            [
                [
                    (
                        self.height
                        - (i * self.channel_height + self.channel_height / 2),
                        f"Ch {i + 1}",
                    )
                    for i in range(self.n_channels)
                ]
            ]
        )

        # Time axis
        time_ticks = [(i * self.width / 5, f"{i}s") for i in range(6)]
        self.plot.getAxis("bottom").setTicks([time_ticks])

        # Colormap - different color for each channel
        # Each channel gets its own color range: ch0=0.0-0.2, ch1=0.2-0.4, etc.
        channel_colors = [
            (255, 100, 100),  # Red/pink for channel 0
            (100, 255, 100),  # Green for channel 1
            (100, 150, 255),  # Blue for channel 2
            (255, 255, 100),  # Yellow for channel 3
            (255, 100, 255),  # Magenta for channel 4
        ]

        # Create color positions and colors list
        colors = [(0, 0, 0)]  # Black background
        positions = [0.0]

        for i in range(self.n_channels):
            base_pos = 0.2 + (
                i * 0.16
            )  # Each channel gets 0.16 range (0.8 total / 5 channels)
            # Add darker and brighter versions of each channel color
            r, g, b = channel_colors[i % len(channel_colors)]

            # Darker version (low intensity)
            colors.append((r // 3, g // 3, b // 3))
            positions.append(base_pos)

            # Medium version
            colors.append((r // 2, g // 2, b // 2))
            positions.append(base_pos + 0.05)

            # Bright version (high intensity)
            colors.append((r, g, b))
            positions.append(base_pos + 0.15)

        cmap = pg.ColorMap(pos=positions, color=colors)
        self.img_item.setLookupTable(cmap.getLookupTable(alpha=True))

        # Set initial black image with correct orientation
        self.img_item.setImage(self.image_data.T)  # Transpose for ImageItem

        # Scale the image to fit the plot
        self.plot.setXRange(0, self.width)
        self.plot.setYRange(0, self.height)

        # Invert Y axis so channel 1 is at top
        self.plot.invertY(True)

        # Controls
        control_layout = QtWidgets.QHBoxLayout()

        # Gain control
        self.gain_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.gain_slider.setRange(1, 100)
        self.gain_slider.setValue(50)
        self.gain_label = QtWidgets.QLabel("Gain: 50")
        self.gain_slider.valueChanged.connect(self.update_gain)

        control_layout.addWidget(QtWidgets.QLabel("Gain:"))
        control_layout.addWidget(self.gain_slider)
        control_layout.addWidget(self.gain_label)
        control_layout.addStretch()

        layout.addLayout(control_layout)

    def update_gain(self, value):
        """Update display gain"""
        self.gain_label.setText(f"Gain: {value}")
        # The gain will be applied when processing new data

    def add_samples(self, channel_data):
        """Add new samples from protobuf frame

        Args:
            channel_data: numpy array of shape (n_channels, n_samples)
        """
        # Process each sample
        for sample_idx in range(channel_data.shape[1]):
            # Add sample from each channel to buffer
            for ch in range(self.n_channels):
                self.data_buffer.append(channel_data[ch, sample_idx])

        # Process buffer when we have enough samples
        while len(self.data_buffer) >= self.downsample * self.n_channels:
            # Extract samples for one pixel column
            pixel_samples = []
            for _ in range(self.downsample * self.n_channels):
                pixel_samples.append(self.data_buffer.popleft())
            pixel_samples = np.array(pixel_samples)

            # Reshape to channels x samples
            pixel_samples = pixel_samples.reshape(self.downsample, self.n_channels).T

            # Apply gain and center around channel middle
            gain = self.gain_slider.value() / 50.0  # More sensitive gain

            # Clear the column first (black background)
            self.image_data[:, self.write_pos] = 0

            # Draw continuous waveform for each channel with different colors
            for ch in range(self.n_channels):
                channel_center = ch * self.channel_height + self.channel_height // 2
                channel_top = ch * self.channel_height + 5  # Leave some margin
                channel_bottom = (ch + 1) * self.channel_height - 5

                # Calculate color value range for this channel
                # Channel 0: 0.2-0.35, Channel 1: 0.36-0.51, etc.
                color_base = 0.2 + (ch * 0.16)
                color_range = 0.15  # Range within each channel's color space

                # Scale the signal data appropriately
                channel_data = pixel_samples[ch] * gain / 1500.0  # Scale for visibility

                # Use more of the channel height for better signal visibility
                max_amplitude = (
                    self.channel_height - 10
                ) // 2  # Use most of channel height

                # Downsample the data to create a smooth waveform representation
                # Take several evenly spaced samples across the pixel column time
                n_points = min(20, len(channel_data))  # Use up to 20 points per pixel
                if len(channel_data) > n_points:
                    indices = np.linspace(0, len(channel_data) - 1, n_points, dtype=int)
                    channel_data = channel_data[indices]

                # Convert samples to pixel positions
                y_positions = []
                for sample in channel_data:
                    y_offset = int(sample * max_amplitude)
                    y_pos = channel_center + y_offset
                    # Clamp to channel bounds
                    y_pos = max(channel_top, min(channel_bottom, y_pos))
                    y_positions.append(y_pos)

                # Draw the waveform with channel-specific colors
                if len(y_positions) > 1:
                    # Method 1: Fill between min and max (thick line effect)
                    min_y = min(y_positions)
                    max_y = max(y_positions)

                    # Draw the main signal band
                    for y in range(min_y, max_y + 1):
                        # Intensity based on distance from the mean
                        mean_y = np.mean(y_positions)
                        distance_from_mean = abs(y - mean_y)
                        relative_intensity = max(
                            0.2, 1.0 - distance_from_mean / max(1, max_y - min_y)
                        )

                        # Map to this channel's color range
                        color_value = color_base + (relative_intensity * color_range)
                        self.image_data[y, self.write_pos] = color_value

                    # Method 2: Also draw connecting lines between consecutive points
                    for i in range(len(y_positions) - 1):
                        y1, y2 = y_positions[i], y_positions[i + 1]
                        # Draw line between consecutive points
                        start_y, end_y = min(y1, y2), max(y1, y2)
                        for y in range(start_y, end_y + 1):
                            # Higher intensity for connecting lines
                            color_value = color_base + (0.8 * color_range)
                            self.image_data[y, self.write_pos] = max(
                                color_value, self.image_data[y, self.write_pos]
                            )

                    # Highlight the actual sample points
                    for y_pos in y_positions[::3]:  # Every 3rd point
                        if channel_top <= y_pos <= channel_bottom:
                            # Maximum intensity for sample points
                            color_value = color_base + color_range
                            self.image_data[y_pos, self.write_pos] = color_value

                elif len(y_positions) == 1:
                    # Single point - draw it with some thickness
                    y_pos = y_positions[0]
                    color_value = color_base + (0.6 * color_range)
                    for dy in range(-1, 2):
                        if channel_top <= y_pos + dy <= channel_bottom:
                            self.image_data[y_pos + dy, self.write_pos] = color_value

            # Debug - print first few pixels
            if self.pixels_written < 5:
                print(
                    f"Pixel {self.pixels_written}: processing column {self.write_pos}"
                )

            # Clear a few pixels ahead of the sweep line for visibility
            clear_pos = (self.write_pos + 2) % self.width
            for i in range(3):
                self.image_data[:, (clear_pos + i) % self.width] = 0

            # Move write position
            self.write_pos = (self.write_pos + 1) % self.width
            self.pixels_written += 1

            # Progress update
            if self.pixels_written % 200 == 0:
                print(
                    f"Written {self.pixels_written} pixels, buffer size: {len(self.data_buffer)}"
                )

    def update_display(self):
        """Update only the image and sweep line position"""
        # Update image - transpose because ImageItem expects (X, Y) not (Y, X)
        self.img_item.setImage(self.image_data.T, autoLevels=True)

        # Update sweep line position
        self.sweep_line.setPos(self.write_pos)


class NeuralDataReceiver:
    """Handles ZMQ reception and protobuf parsing"""

    def __init__(self, display, zmq_address="tcp://localhost:5555"):
        self.display = display
        self.tap = Tap("10.40.61.119", verbose=True)
        self.tap.connect("broadband_source_2")
        self.running = False
        self.thread = None

    def start(self):
        """Start receiving data"""
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop receiving data"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)

    def _receive_loop(self):
        """Main reception loop"""
        # Setup ZMQ

        while self.running:
            try:
                # Receive raw message
                for message in self.tap.stream():
                    frame = BroadbandFrameProto()
                    frame.ParseFromString(message)
                    # Get the first five channels
                    frame_data = np.array(frame.frame_data[:5]).reshape(5, -1)
                    self.display.add_samples(frame_data)

                # # Parse protobuf
                # # frame = BroadbandFrame()
                # # frame.ParseFromString(raw_message)

                # # For testing without protobuf - simulate data
                # frame_data = np.random.randn(5 * 32).astype(np.float32) * 100
                # frame_data = frame_data + np.sin(np.arange(5 * 32) * 0.1) * 200

                # # Reshape to channels x samples
                # n_samples = len(frame_data) // self.display.n_channels
                # channel_data = frame_data.reshape(n_samples, self.display.n_channels).T

                # # Add to display
                # self.display.add_samples(channel_data)

            except Exception as e:
                print(f"Error receiving data: {e}")


def main():
    """Main application"""
    import sys

    app = QtWidgets.QApplication.instance()
    if not app:
        app = QtWidgets.QApplication(sys.argv)

    # Create display
    display = NeuralRasterDisplay(n_channels=5, sample_rate=32000, display_seconds=5)
    display.show()

    # Create receiver (comment out if you want to test without ZMQ)
    receiver = NeuralDataReceiver(display)
    receiver.start()

    # For testing - simulate data
    # def simulate_data():
    #     while True:
    #         # Simulate 1ms of data (32 samples per channel)
    #         n_samples = 32
    #         channel_data = np.zeros((5, n_samples))

    #         for ch in range(5):
    #             # Different frequency for each channel
    #             t = np.arange(n_samples) / 32000
    #             channel_data[ch] = (
    #                 100 * np.sin(2 * np.pi * (5 + ch * 2) * t) +
    #                 50 * np.random.randn(n_samples)
    #             )

    #             # Random spikes
    #             if np.random.rand() < 0.05:
    #                 channel_data[ch, np.random.randint(n_samples)] = np.random.choice([-500, 500])

    #         display.add_samples(channel_data)
    #         time.sleep(0.001)  # 1ms

    # sim_thread = threading.Thread(target=simulate_data, daemon=True)
    # sim_thread.start()

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        # receiver.stop()
        pass


if __name__ == "__main__":
    main()
