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

        # One ring buffer (of length BUFFER_SIZE) per channel
        self.data_buffers = [
            np.zeros(self.buffer_size) for _ in range(self.num_channels)
        ]

        # Timestamp buffer for each channel (in seconds, relative to start)
        self.timestamp_buffers = [
            np.zeros(self.buffer_size) for _ in range(self.num_channels)
        ]

        # A separate ring-buffer pointer for each channel
        self.buffer_positions = [0] * self.num_channels

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

        # Dictionary to store line series for plotted channels
        self.active_lines = {}

        # Queue and threading for BroadbandFrame processing
        self.data_queue = queue.Queue(maxsize=2000)
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

            # Zoomed Channel Y-range
            dpg.add_text("Zoomed Y-Axis Range (Manual):")
            dpg.add_input_float(
                label="Min",
                default_value=self.zoom_y_min,
                callback=self.set_zoom_y_min,
                tag="zoom_y_min_input",
            )
            dpg.add_input_float(
                label="Max",
                default_value=self.zoom_y_max,
                callback=self.set_zoom_y_max,
                tag="zoom_y_max_input",
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

    def set_zoom_y_min(self, sender, app_data):
        self.zoom_y_min = app_data

    def set_zoom_y_max(self, sender, app_data):
        self.zoom_y_max = app_data

    def set_signal_separation(self, sender, app_data):
        self.signal_separation = app_data

    def put(self, frame: BroadbandFrame):
        """Add a BroadbandFrame to the processing queue"""
        try:
            self.data_queue.put(frame, block=False)
        except queue.Full:
            # If queue is full, drop multiple old frames and add the new one
            dropped = 0
            while dropped < 5:  # Drop up to 5 old frames
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

        # Main loop
        fps_limit = 30
        frame_duration = 1.0 / fps_limit
        last_time = time.time()

        while dpg.is_dearpygui_running() and not self.stop_event.is_set():
            # Process multiple frames per iteration for better throughput
            frames_processed = 0
            max_frames_per_iter = 10

            while frames_processed < max_frames_per_iter:
                try:
                    frame = self.data_queue.get_nowait()
                    self.process_broadband_frame(frame)
                    frames_processed += 1
                except queue.Empty:
                    break

            # Throttle rendering to the fps limit
            now = time.time()
            if (now - last_time) >= frame_duration:
                self.update_plot()
                dpg.render_dearpygui_frame()
                last_time = now

        dpg.destroy_context()

    def update_plot(self):
        """
        Update both the 'all channels' plot and the 'single channel' zoom plot.
        We 'roll' each channel's data so that the newest sample is on the right.
        """
        # Downsample factor for performance
        # Note(gilbert): we should probably make this configurable, it is arbitrary
        ds_factor = 4

        # Get the current time window for x-axis limits based on latest data
        # Use latest data timestamp instead of wall clock for better sync
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
            pos = self.buffer_positions[idx]

            # Roll data so that index -1 corresponds to the newest sample
            rolled_y = np.roll(self.data_buffers[idx], -pos)
            rolled_x = np.roll(self.timestamp_buffers[idx], -pos)

            # Downsample
            ds_x = rolled_x[::ds_factor]
            ds_y = rolled_y[::ds_factor]

            # Apply vertical offset for each active channel to avoid overlap
            offset = active_channel_idx * self.signal_separation
            ds_y_offset = ds_y + offset

            # Update the line series for this channel
            line_tag = self.active_lines[ch_id]
            dpg.set_value(line_tag, [ds_x.tolist(), ds_y_offset.tolist()])

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
        pos = self.buffer_positions[idx]

        rolled_y_ch = np.roll(self.data_buffers[idx], -pos)
        rolled_x_ch = np.roll(self.timestamp_buffers[idx], -pos)

        ds_x_ch = rolled_x_ch[::ds_factor]
        ds_y_ch = rolled_y_ch[::ds_factor]

        # Update the single "zoomed_line" series
        dpg.set_value("zoomed_line", [ds_x_ch.tolist(), ds_y_ch.tolist()])

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
        Uses actual timestamps from the frame for proper time synchronization.
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
        # We assume the data is organized as: [ch0_sample, ch1_sample, ch2_sample, ...]
        frame_data = frame.frame_data

        # Distribute data to each channel buffer
        for ch_idx, ch_id in enumerate(self.channel_ids):
            if ch_idx < len(frame_data):
                sample = frame_data[ch_idx]

                # Add sample to this channel's ring buffer
                pos = self.buffer_positions[ch_idx]
                self.data_buffers[ch_idx][pos] = sample

                # Add actual timestamp to this channel's timestamp buffer
                self.timestamp_buffers[ch_idx][pos] = relative_time_s

                self.buffer_positions[ch_idx] = (pos + 1) % self.buffer_size

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
