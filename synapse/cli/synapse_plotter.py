import dearpygui.dearpygui as dpg
import queue
import time
from threading import Event, Thread
import numpy as np
from synapse.api.datatype_pb2 import BroadbandFrame


class SynapsePlotter:
    def __init__(self, sample_rate: int, window_size: int, channel_ids):
        self.num_channels = len(channel_ids)
        self.sample_rate_hz = sample_rate
        self.window_size_seconds = window_size
        self.buffer_size = self.sample_rate_hz * self.window_size_seconds
        self.channel_ids = channel_ids

        # Create a mapping from channel ID to buffer index
        self.channel_to_index = {
            ch_id: idx for idx, ch_id in enumerate(self.channel_ids)
        }

        # Track which channels are selected for plotting (start with first 5)
        self.selected_channels = set(self.channel_ids[:5])

        # Optimized ring buffers - use circular indexing instead of rolling
        self.data_buffers = np.zeros(
            (self.num_channels, self.buffer_size), dtype=np.float32
        )
        self.timestamp_buffers = np.zeros(
            (self.num_channels, self.buffer_size), dtype=np.float64
        )

        # Single shared write position for all channels (assuming synchronized data)
        self.write_position = 0
        self.buffer_filled = False  # Track if we've wrapped around once

        # Track which channel to display in the "zoom" (single channel) plot
        self.selected_channel_idx = 0
        self.selected_channel_id = self.channel_ids[0]

        # Track start time for display and timestamp conversion
        self.start_time = None
        self.start_timestamp_ns = None
        self.latest_data_time = 0  # Track the most recent data timestamp in seconds

        # Defaults for the zoomed channel plot
        self.zoom_y_min = -4096
        self.zoom_y_max = 4096

        self.signal_separation = 1000
        self.downsample_factor = 4  # Default downsample factor for performance
        self.center_data = (
            True  # Whether to center data around zero by removing DC offset
        )

        # Dictionary to store line series for plotted channels
        self.active_lines = {}

        # Optimized running statistics for centering data
        self.running_means = np.zeros(self.num_channels, dtype=np.float32)
        self.sample_counts = np.zeros(self.num_channels, dtype=np.int64)
        self.alpha = 0.001  # Low-pass filter coefficient for running mean

        # Pre-allocated arrays for plotting to avoid memory allocations
        self.plot_x_buffer = np.zeros(
            self.buffer_size // self.downsample_factor, dtype=np.float64
        )
        self.plot_y_buffer = np.zeros(
            self.buffer_size // self.downsample_factor, dtype=np.float32
        )

        # Adaptive update frequency
        self.last_update_time = 0
        self.min_update_interval = 1.0 / 60.0  # Max 60 FPS
        self.frames_since_update = 0
        self.update_every_n_frames = 5  # Update every N frames by default

        # Queue and threading for BroadbandFrame processing
        self.data_queue = queue.Queue(maxsize=5000)  # Larger queue
        self.stop_event = Event()
        self.plot_thread = None
        self.running = False

        dpg.create_context()
        self.setup_gui()

    def setup_gui(self):
        """Builds the DearPyGui layout."""
        dpg.create_viewport(title="SciFi Data Viewer", width=1280, height=720)

        # -----------------------------
        # Controls Window (left side)
        # -----------------------------
        with dpg.window(
            label="Controls",
            width=200,
            no_resize=True,
            pos=(0, 0),
            tag="control_window",
        ):
            dpg.add_text("Select Channels to Plot:")

            # Add convenience buttons
            with dpg.group(horizontal=True):
                dpg.add_button(label="All", callback=self.select_all_channels, width=40)
                dpg.add_button(label="None", callback=self.select_no_channels, width=40)
                dpg.add_button(
                    label="First 5", callback=self.select_first_5_channels, width=50
                )

            # Add checkboxes for each channel in a scrollable region
            with dpg.child_window(height=150, tag="channel_selection"):
                for ch_id in self.channel_ids:
                    is_selected = ch_id in self.selected_channels
                    dpg.add_checkbox(
                        label=f"Channel {ch_id}",
                        default_value=is_selected,
                        callback=self.channel_checkbox_callback,
                        user_data=ch_id,
                        tag=f"ch_checkbox_{ch_id}",
                    )

            dpg.add_separator()
            dpg.add_text("Select Channel to Zoom:")
            dpg.add_combo(
                items=[str(ch_id) for ch_id in self.channel_ids],
                default_value=str(self.selected_channel_id),
                callback=self.zoom_channel_callback,
                tag="zoom_channel_combo",
                width=80,
            )

            dpg.add_separator()
            dpg.add_text("Elapsed Time (s):")
            dpg.add_text("", tag="elapsed_time_text")

            dpg.add_text("Signal Separation:")
            dpg.add_input_int(
                label="",
                default_value=self.signal_separation,
                tag="signal_separation_input",
                callback=self.set_signal_separation,
            )

            dpg.add_text("Downsample Factor:")
            dpg.add_input_int(
                label="",
                default_value=self.downsample_factor,
                min_value=1,
                max_value=20,
                tag="downsample_factor_input",
                callback=self.set_downsample_factor,
            )

            dpg.add_separator()
            dpg.add_checkbox(
                label="Center Data Around Zero",
                default_value=self.center_data,
                callback=self.set_center_data,
                tag="center_data_checkbox",
            )

            # Zoomed Channel Y-range
            dpg.add_text("Zoomed Y-Axis Range (±):")
            dpg.add_input_float(
                label="Range",
                default_value=abs(self.zoom_y_max),
                callback=self.set_zoom_y_range,
                tag="zoom_y_range_input",
                min_value=1.0,
            )

        # -----------------------------
        # Main Data Window (plots)
        # -----------------------------
        with dpg.window(
            label="Neural Data",
            width=1080,
            height=700,
            pos=(200, 0),
            no_close=True,
            tag="main_window",
        ):
            with dpg.tab_bar():
                # All Channels Tab
                with dpg.tab(label="All Channels"):
                    with dpg.plot(
                        label="Neural Activity (All)",
                        height=-1,
                        width=-1,
                        tag="all_channels_plot",
                    ):
                        dpg.add_plot_legend()

                        # Axes
                        dpg.add_plot_axis(
                            dpg.mvXAxis, label="Time (s)", tag="x_axis_all"
                        )
                        self.y_axis_all = dpg.add_plot_axis(
                            dpg.mvYAxis, label="Amplitude", tag="y_axis_all"
                        )
                        dpg.set_axis_limits("y_axis_all", -4096, 4096 * 10)

                        # Create line series for initially selected channels
                        for ch_id in self.selected_channels:
                            self.create_line_series(ch_id)

                # Zoomed Channel Tab
                with dpg.tab(label="Zoomed Channel"):
                    with dpg.plot(
                        label="Zoomed Channel Plot",
                        height=-1,
                        width=-1,
                        tag="zoomed_plot",
                    ):
                        dpg.add_plot_legend()

                        # Axes
                        dpg.add_plot_axis(
                            dpg.mvXAxis, label="Time (s)", tag="x_axis_zoom"
                        )
                        self.y_axis_zoom = dpg.add_plot_axis(
                            dpg.mvYAxis, label="Amplitude", tag="y_axis_zoom"
                        )

                        # Single line series for the "zoomed" channel
                        dpg.add_line_series(
                            [],
                            [],
                            label=f"Channel {self.selected_channel_id}",
                            parent=self.y_axis_zoom,
                            tag="zoomed_line",
                        )

    def channel_checkbox_callback(self, sender, app_data, user_data):
        """Called when user checks/unchecks a channel checkbox."""
        ch_id = user_data
        if app_data:  # Checked
            self.selected_channels.add(ch_id)
            self.create_line_series(ch_id)
        else:  # Unchecked
            self.selected_channels.discard(ch_id)
            self.remove_line_series(ch_id)

    def zoom_channel_callback(self, sender, app_data, user_data):
        """Called when user picks a channel for zooming."""
        self.selected_channel_id = int(app_data)
        self.selected_channel_idx = self.channel_to_index[self.selected_channel_id]
        # Update the label of the zoomed line
        dpg.configure_item("zoomed_line", label=f"Channel {self.selected_channel_id}")

    def create_line_series(self, ch_id):
        """Create a line series for the specified channel."""
        if ch_id not in self.active_lines:
            line_tag = f"all_line_ch{ch_id}"
            dpg.add_line_series(
                [],
                [],
                label=f"Ch {ch_id}",
                parent=self.y_axis_all,
                tag=line_tag,
            )
            self.active_lines[ch_id] = line_tag

    def remove_line_series(self, ch_id):
        """Remove the line series for the specified channel."""
        if ch_id in self.active_lines:
            line_tag = self.active_lines[ch_id]
            dpg.delete_item(line_tag)
            del self.active_lines[ch_id]

    def set_zoom_y_range(self, sender, app_data):
        # Ensure the range is centered around zero
        abs_range = abs(app_data)
        self.zoom_y_min = -abs_range
        self.zoom_y_max = abs_range

    def set_signal_separation(self, sender, app_data):
        self.signal_separation = app_data

    def set_downsample_factor(self, sender, app_data):
        # Ensure the downsample factor is at least 1
        self.downsample_factor = max(1, app_data)
        # Reallocate plot buffers if needed
        new_size = self.buffer_size // self.downsample_factor
        if len(self.plot_x_buffer) != new_size:
            self.plot_x_buffer = np.zeros(new_size, dtype=np.float64)
            self.plot_y_buffer = np.zeros(new_size, dtype=np.float32)

    def set_center_data(self, sender, app_data):
        self.center_data = app_data
        if not app_data:
            # Reset running means when centering is disabled
            self.running_means.fill(0.0)
            self.sample_counts.fill(0)

    def put(self, frame: BroadbandFrame):
        """Add a BroadbandFrame to the processing queue"""
        try:
            self.data_queue.put(frame, block=False)
        except queue.Full:
            # If queue is full, drop multiple old frames and add the new one
            dropped = 0
            while dropped < 10:  # Drop up to 10 old frames
                try:
                    self.data_queue.get_nowait()
                    dropped += 1
                except queue.Empty:
                    break
            try:
                self.data_queue.put(frame, block=False)
            except queue.Full:
                pass  # Still full, drop this frame

    def put_batch(self, frames: list):
        """Add multiple BroadbandFrames efficiently"""
        for frame in frames:
            try:
                self.data_queue.put(frame, block=False)
            except queue.Full:
                # Drop old frames to make room
                try:
                    self.data_queue.get_nowait()
                    self.data_queue.put(frame, block=False)
                except queue.Empty:
                    pass

    def start(self):
        """Start the plotter in a separate thread"""
        if self.running:
            return

        self.running = True
        self.stop_event.clear()
        self.plot_thread = Thread(target=self._plot_thread_main)
        self.plot_thread.start()

    def stop(self):
        """Stop the plotter thread"""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()
        if self.plot_thread:
            self.plot_thread.join()

    def _plot_thread_main(self):
        """Main plotting thread that runs the DearPyGui event loop"""
        dpg.setup_dearpygui()
        dpg.show_viewport()

        # Record start time
        self.start_time = time.time()

        while dpg.is_dearpygui_running() and not self.stop_event.is_set():
            # Process ALL available frames per iteration for maximum throughput
            frames_processed = 0
            max_frames_per_iter = 50  # Increased batch size

            while frames_processed < max_frames_per_iter:
                try:
                    frame = self.data_queue.get_nowait()
                    self.process_broadband_frame(frame)
                    frames_processed += 1
                except queue.Empty:
                    break

            self.frames_since_update += frames_processed

            # Adaptive update frequency - only update when necessary
            now = time.time()
            should_update = (
                (now - self.last_update_time) >= self.min_update_interval
                and self.frames_since_update >= self.update_every_n_frames
            )

            if should_update or frames_processed == 0:
                self.update_plot()
                dpg.render_dearpygui_frame()
                self.last_update_time = now
                self.frames_since_update = 0

                # Adaptive update frequency based on processing load
                if frames_processed > 30:
                    self.update_every_n_frames = min(20, self.update_every_n_frames + 1)
                elif frames_processed < 5:
                    self.update_every_n_frames = max(1, self.update_every_n_frames - 1)
            else:
                # Still need to render DearPyGui even if not updating plots
                dpg.render_dearpygui_frame()

        dpg.destroy_context()

    def _get_circular_data(self, channel_idx, downsample=True):
        """Efficiently get data from circular buffer without copying the entire array"""
        # Get the data and timestamp buffers for this channel
        data_buf = self.data_buffers[channel_idx]
        time_buf = self.timestamp_buffers[channel_idx]

        if not self.buffer_filled:
            # Buffer hasn't wrapped yet, just use data from 0 to write_position
            end_idx = self.write_position
            if downsample:
                step = self.downsample_factor
                data_slice = data_buf[:end_idx:step]
                time_slice = time_buf[:end_idx:step]
            else:
                data_slice = data_buf[:end_idx]
                time_slice = time_buf[:end_idx]
        else:
            # Buffer has wrapped, need to get data in correct time order
            if downsample:
                step = self.downsample_factor
                # Get newer data (from write_position to end)
                newer_data = data_buf[self.write_position :: step]
                newer_time = time_buf[self.write_position :: step]
                # Get older data (from start to write_position)
                older_data = data_buf[: self.write_position : step]
                older_time = time_buf[: self.write_position : step]
                # Concatenate in chronological order
                data_slice = np.concatenate([newer_data, older_data])
                time_slice = np.concatenate([newer_time, older_time])
            else:
                newer_data = data_buf[self.write_position :]
                newer_time = time_buf[self.write_position :]
                older_data = data_buf[: self.write_position]
                older_time = time_buf[: self.write_position]
                data_slice = np.concatenate([newer_data, older_data])
                time_slice = np.concatenate([newer_time, older_time])

        return time_slice, data_slice

    def update_plot(self):
        """
        Update both the 'all channels' plot and the 'single channel' zoom plot.
        Optimized to avoid expensive operations.
        """
        # Get the current time window for x-axis limits based on latest data
        current_data_time = self.latest_data_time
        x_min = max(0, current_data_time - self.window_size_seconds)
        x_max = current_data_time

        # -----------------------------
        # Update "All Channels" Plot
        # -----------------------------
        active_channel_idx = 0
        for ch_id in self.selected_channels:
            if ch_id not in self.active_lines:
                continue

            idx = self.channel_to_index[ch_id]

            # Get data efficiently using circular buffer indexing
            time_data, signal_data = self._get_circular_data(idx, downsample=True)

            if len(signal_data) == 0:
                continue

            # Apply vertical offset for each active channel to avoid overlap
            offset = active_channel_idx * self.signal_separation
            signal_data_offset = signal_data + offset

            # Update the line series for this channel
            line_tag = self.active_lines[ch_id]
            dpg.set_value(line_tag, [time_data.tolist(), signal_data_offset.tolist()])

            active_channel_idx += 1

        # Set X-axis limits to show current time window
        dpg.set_axis_limits("x_axis_all", x_min, x_max)

        # Set Y-axis limits based on number of active channels
        num_active = len(self.selected_channels)
        if num_active > 0:
            y_max_all = (num_active - 1) * self.signal_separation + 4096
            y_min_all = -4096
            dpg.set_axis_limits("y_axis_all", y_min_all, y_max_all)

        # -----------------------------
        # Update Zoomed Channel Plot
        # -----------------------------
        idx = self.selected_channel_idx
        time_data_zoom, signal_data_zoom = self._get_circular_data(idx, downsample=True)

        if len(signal_data_zoom) > 0:
            # Update the single "zoomed_line" series
            dpg.set_value(
                "zoomed_line", [time_data_zoom.tolist(), signal_data_zoom.tolist()]
            )

        # Set axis limits for both plots
        dpg.set_axis_limits("x_axis_zoom", x_min, x_max)
        dpg.set_axis_limits("y_axis_zoom", self.zoom_y_min, self.zoom_y_max)

        # -----------------------------
        # Update Elapsed Time Text
        # -----------------------------
        if self.start_time is not None:
            elapsed = time.time() - self.start_time
            dpg.set_value("elapsed_time_text", f"{elapsed:.2f}")

    def process_broadband_frame(self, frame: BroadbandFrame):
        """
        Process a BroadbandFrame and distribute the data to channel buffers.
        Optimized for high throughput.
        """
        # Set start timestamp on first frame
        if self.start_timestamp_ns is None:
            self.start_timestamp_ns = frame.timestamp_ns
            self.start_time = time.time()

        # Convert timestamp to seconds relative to start
        relative_time_s = (frame.timestamp_ns - self.start_timestamp_ns) / 1e9

        # Update latest data time
        self.latest_data_time = relative_time_s

        # frame_data is a flat array with one sample per channel
        frame_data = frame.frame_data
        num_samples = min(len(frame_data), self.num_channels)

        if num_samples == 0:
            return

        # Vectorized processing for all channels at once
        raw_samples = np.array(frame_data[:num_samples], dtype=np.float32)

        # Center data around zero if enabled - vectorized operation
        if self.center_data:
            # Update running means with exponential moving average - vectorized
            mask = self.sample_counts[:num_samples] == 0
            self.running_means[:num_samples][mask] = raw_samples[mask]
            self.running_means[:num_samples][~mask] = (
                1 - self.alpha
            ) * self.running_means[:num_samples][~mask] + self.alpha * raw_samples[
                ~mask
            ]
            self.sample_counts[:num_samples] += 1

            # Subtract the running mean to center around zero - vectorized
            processed_samples = raw_samples - self.running_means[:num_samples]
        else:
            processed_samples = raw_samples

        # Add samples to ring buffers - vectorized write
        pos = self.write_position
        self.data_buffers[:num_samples, pos] = processed_samples
        self.timestamp_buffers[:num_samples, pos] = relative_time_s

        # Update write position
        self.write_position = (pos + 1) % self.buffer_size
        if pos + 1 >= self.buffer_size:
            self.buffer_filled = True

    def select_all_channels(self):
        """Select all channels for plotting."""
        # Update internal state
        old_selection = self.selected_channels.copy()
        self.selected_channels = set(self.channel_ids)

        # Update checkboxes
        for ch_id in self.channel_ids:
            dpg.set_value(f"ch_checkbox_{ch_id}", True)
            if ch_id not in old_selection:
                self.create_line_series(ch_id)

    def select_no_channels(self):
        """Deselect all channels."""
        # Update internal state
        old_selection = self.selected_channels.copy()
        self.selected_channels = set()

        # Update checkboxes and remove line series
        for ch_id in old_selection:
            dpg.set_value(f"ch_checkbox_{ch_id}", False)
            self.remove_line_series(ch_id)

    def select_first_5_channels(self):
        """Select only the first 5 channels."""
        # Update internal state
        old_selection = self.selected_channels.copy()
        self.selected_channels = set(self.channel_ids[:5])

        # Update checkboxes
        for ch_id in self.channel_ids:
            should_be_selected = ch_id in self.selected_channels
            dpg.set_value(f"ch_checkbox_{ch_id}", should_be_selected)

            if should_be_selected and ch_id not in old_selection:
                self.create_line_series(ch_id)
            elif not should_be_selected and ch_id in old_selection:
                self.remove_line_series(ch_id)


# Factory function to create plotter with BroadbandFrame support
def create_broadband_plotter(
    sample_rate_hz: int, window_size_seconds: int, channel_ids
):
    """Create a SynapsePlotter configured for BroadbandFrame data"""
    return SynapsePlotter(sample_rate_hz, window_size_seconds, channel_ids)


# Legacy function for backward compatibility
def plot_synapse_data(
    stop: Event,
    data_queue: queue.Queue,
    sample_rate_hz: int,
    window_size_seconds: int,
    channel_ids,
):
    plotter = SynapsePlotter(sample_rate_hz, window_size_seconds, channel_ids)
    plotter.start(stop, data_queue)
