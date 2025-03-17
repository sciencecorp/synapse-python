import dearpygui.dearpygui as dpg
import queue
import time
from threading import Event
import numpy as np


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

        # One ring buffer (of length BUFFER_SIZE) per channel
        self.data_buffers = [
            np.zeros(self.buffer_size) for _ in range(self.num_channels)
        ]

        # A time axis (0..WINDOW_SIZE) also size BUFFER_SIZE
        self.time_buffer = np.linspace(
            0, self.window_size_seconds, self.buffer_size, endpoint=True
        )

        # A separate ring-buffer pointer for each channel
        # TODO(gilbert): this is assuming that channels are truly independent
        self.buffer_positions = [0] * self.num_channels

        # Track which channel to display in the "zoom" (single channel) plot
        self.selected_channel_idx = 0
        self.selected_channel_id = self.channel_ids[0]

        # Track start time for display
        self.start_time = None

        # Defaults for the zoomed channel plot
        self.zoom_y_min = 0
        self.zoom_y_max = 4096

        self.signal_separation = 1000

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
            dpg.add_text("Select Channel to Zoom:")
            dpg.add_combo(
                items=[str(ch_id) for ch_id in self.channel_ids],
                default_value=str(self.selected_channel_id),
                callback=self.channel_selection_callback,
                tag="channel_combo",
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
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)")
                        self.y_axis_all = dpg.add_plot_axis(
                            dpg.mvYAxis, label="Amplitude", tag="y_axis_all"
                        )
                        dpg.set_axis_limits("y_axis_all", 0, 4096 * 10)

                        # Create line series for each channel
                        self.lines_all = []
                        for idx, ch_id in enumerate(self.channel_ids):
                            line_tag = f"all_line_ch{ch_id}"
                            line = dpg.add_line_series(
                                [],
                                [],
                                label=f"Ch {ch_id}",
                                parent=self.y_axis_all,
                                tag=line_tag,
                            )
                            self.lines_all.append(line)

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
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)")
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

    def channel_selection_callback(self, sender, app_data, user_data):
        """Called when user picks a channel from the combo."""
        self.selected_channel_id = int(app_data)
        self.selected_channel_idx = self.channel_to_index[self.selected_channel_id]
        # Update the label of the zoomed line
        dpg.configure_item("zoomed_line", label=f"Channel {self.selected_channel_id}")

    def set_zoom_y_min(self, sender, app_data):
        self.zoom_y_min = app_data

    def set_zoom_y_max(self, sender, app_data):
        self.zoom_y_max = app_data

    def set_signal_separation(self, sender, app_data):
        self.signal_separation = app_data

    def on_split_drag(self, sender, app_data):
        """Handle dragging the splitter between plots."""
        # Get the main window height
        main_window_height = dpg.get_item_height("main_window")

        # Calculate new heights based on drag position
        mouse_pos = dpg.get_mouse_pos(local=False)
        window_pos = dpg.get_item_pos("main_window")
        relative_height = mouse_pos[1] - window_pos[1]

        # Ensure minimum heights for both windows
        MIN_HEIGHT = 100
        if (
            relative_height < MIN_HEIGHT
            or relative_height > main_window_height - MIN_HEIGHT
        ):
            return

        # Update the heights of both windows
        dpg.configure_item("top_plot_window", height=relative_height)

    def resize_callback(self, sender, app_data):
        """Handle window resize events."""
        viewport_width = dpg.get_viewport_width()
        viewport_height = dpg.get_viewport_height()

        # Update main window size
        main_window_width = viewport_width - 280  # Leave space for control window
        main_window_height = viewport_height - 20  # Leave small margin
        dpg.configure_item(
            "main_window", width=main_window_width, height=main_window_height
        )

    def update_plot(self):
        """
        Update both the 'all channels' plot and the 'single channel' zoom plot.
        We 'roll' each channel's data so that the newest sample is on the right.
        """
        # Downsample factor for performance
        # Note(gilbert): we should probably make this configurable, it is arbitrary
        ds_factor = 10

        # -----------------------------
        # Update "All Channels" Plot
        # -----------------------------
        for idx, ch_id in enumerate(self.channel_ids):
            pos = self.buffer_positions[idx]

            # Roll data so that index -1 corresponds to the newest sample
            rolled_y = np.roll(self.data_buffers[idx], -pos)
            rolled_x = np.roll(self.time_buffer, -pos)

            # Downsample
            ds_x = rolled_x[::ds_factor]
            ds_y = rolled_y[::ds_factor]

            # Apply vertical offset for each channel to avoid overlap
            offset = idx * self.signal_separation
            ds_y_offset = ds_y + offset

            # Update the line series for channel ch
            dpg.set_value(self.lines_all[idx], [ds_x.tolist(), ds_y_offset.tolist()])

        # -----------------------------
        # Update Zoomed Channel Plot
        # -----------------------------
        idx = self.selected_channel_idx
        pos = self.buffer_positions[idx]

        rolled_y_ch = np.roll(self.data_buffers[idx], -pos)
        rolled_x_ch = np.roll(self.time_buffer, -pos)

        ds_x_ch = rolled_x_ch[::ds_factor]
        ds_y_ch = rolled_y_ch[::ds_factor]

        # Update the single "zoomed_line" series
        dpg.set_value("zoomed_line", [ds_x_ch.tolist(), ds_y_ch.tolist()])

        # Optionally set the zoomed plot Y-axis range for a closer look
        dpg.set_axis_limits("y_axis_zoom", self.zoom_y_min, self.zoom_y_max)

        # -----------------------------
        # Update Elapsed Time Text
        # -----------------------------
        if self.start_time is not None:
            elapsed = time.time() - self.start_time
            dpg.set_value("elapsed_time_text", f"{elapsed:.2f}")

    def process_data(self, data):
        """
        data = (channel, samples)
        Write these samples into the ring buffer for that channel.
        """
        channel_id, samples = data
        if channel_id not in self.channel_to_index:
            print(
                f"Warning: Received data for channel {channel_id} which is not in the configured channel list."
            )
            return

        # Get our channel id mapped to our plotting index
        idx = self.channel_to_index[channel_id]
        num_samples = len(samples)
        pos = self.buffer_positions[idx]

        end_pos = pos + num_samples
        if end_pos <= self.buffer_size:
            # Simple case: fits without wrap
            self.data_buffers[idx][pos:end_pos] = samples
        else:
            # Wrap around case
            first_part = self.buffer_size - pos
            second_part = num_samples - first_part
            self.data_buffers[idx][pos:] = samples[:first_part]
            self.data_buffers[idx][:second_part] = samples[first_part:]

        self.buffer_positions[idx] = (pos + num_samples) % self.buffer_size

    def start(self, stop, data_queue):
        """Run the DearPyGui event/render loop."""
        dpg.setup_dearpygui()
        dpg.show_viewport()

        # Record start time
        self.start_time = time.time()

        # Main loop
        fps_limit = 60
        frame_duration = 1.0 / fps_limit
        last_time = time.time()

        while dpg.is_dearpygui_running() and not stop.is_set():
            # Process any incoming data in the queue
            while True:
                try:
                    data = data_queue.get_nowait()
                    self.process_data(data.samples[0])
                except queue.Empty:
                    break

            # Throttle rendering to the fps limit
            now = time.time()
            if (now - last_time) >= frame_duration:
                self.update_plot()
                dpg.render_dearpygui_frame()
                last_time = now

        dpg.destroy_context()


def plot_synapse_data(
    stop: Event,
    data_queue: queue.Queue,
    sample_rate_hz: int,
    window_size_seconds: int,
    channel_ids,
):
    plotter = SynapsePlotter(sample_rate_hz, window_size_seconds, channel_ids)
    plotter.start(stop, data_queue)
