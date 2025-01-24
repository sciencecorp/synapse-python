import dearpygui.dearpygui as dpg
import queue
import time
from threading import Event
import numpy as np

class SynapsePlotter:
    def __init__(self, num_channels: int, sample_rate: int, window_size: int):
        self.num_channels = num_channels
        self.sample_rate_hz = sample_rate
        self.window_size_seconds = window_size
        self.buffer_size = self.sample_rate_hz * self.window_size_seconds

        # One ring buffer (of length BUFFER_SIZE) per channel
        self.data_buffers = [np.zeros(self.buffer_size) for _ in range(self.num_channels)]

        # A time axis (0..WINDOW_SIZE) also size BUFFER_SIZE
        self.time_buffer = np.linspace(0, self.window_size_seconds, self.buffer_size, endpoint=True)

        # A separate ring-buffer pointer for each channel
        # TODO(gilbert): this is assuming that channels are truly independent
        self.buffer_positions = [0]*self.num_channels

        # Track which channel to display in the "zoom" (single channel) plot
        self.selected_channel = 0

        # Track start time for display
        self.start_time = None

        # Defaults for the zoomed channel plot
        self.zoom_y_min = 1800
        self.zoom_y_max = 2800

        self.signal_separation = 1000
        
        dpg.create_context()
        self.setup_gui()

    def setup_gui(self):
        """Builds the DearPyGui layout."""
        dpg.create_viewport(title="SciFi Data Viewer", width=1800, height=1300)

        # -----------------------------
        # Controls Window (left side)
        # -----------------------------
        with dpg.window(label="Controls", width=250, height=200, pos=(10, 10)):
            dpg.add_text("Select Channel to Zoom:")
            dpg.add_combo(
                items=[str(i) for i in range(self.num_channels)],
                default_value=str(self.selected_channel),
                callback=self.channel_selection_callback,
                tag="channel_combo",
                width=80
            )
            dpg.add_separator()
            dpg.add_text("Elapsed Time (s):")
            dpg.add_text("", tag="elapsed_time_text")

            dpg.add_text("Signal Separation:")
            dpg.add_input_int(label="", default_value=self.signal_separation, tag="signal_separation_input", callback=self.set_signal_separation)

            # Zoomed Channel Y-range
            dpg.add_text("Zoomed Y-Axis Range (Manual):")
            dpg.add_input_float(label="Min", default_value=self.zoom_y_min, 
                                callback=self.set_zoom_y_min,
                                tag="zoom_y_min_input")
            dpg.add_input_float(label="Max", default_value=self.zoom_y_max, 
                                callback=self.set_zoom_y_max,
                                tag="zoom_y_max_input")
        

        # -----------------------------
        # Main Data Window (plots)
        # -----------------------------
        with dpg.window(label="Neural Data", width=1500, height=1300, pos=(270, 10)):
            
            # ========== TOP PLOT: All Channels ==========
            dpg.add_text("All Channels:")
            with dpg.plot(label="Neural Activity (All)", height=700, width=-1):
                dpg.add_plot_legend()
                
                # Axes
                dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)")
                self.y_axis_all = dpg.add_plot_axis(dpg.mvYAxis, label="Amplitude", tag="y_axis_all")
                dpg.set_axis_limits("y_axis_all", 0, 4096 * 10)  # or adjust range as needed
                
                # Create line series for each channel
                self.lines_all = []
                for ch in range(self.num_channels):
                    line_tag = f"all_line_ch{ch}"
                    line = dpg.add_line_series([], [],
                                               label=f"Ch {ch}",
                                               parent=self.y_axis_all,
                                               tag=line_tag)
                    self.lines_all.append(line)

            dpg.add_separator()
            
            # ========== BOTTOM PLOT: Single (Zoomed) Channel ==========
            dpg.add_text("Zoomed Channel:")
            with dpg.plot(label="Zoomed Channel Plot", height=350, width=-1):
                dpg.add_plot_legend()
                
                # Axes
                dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)")
                self.y_axis_zoom = dpg.add_plot_axis(dpg.mvYAxis, label="Amplitude", tag="y_axis_zoom")
                
                # Single line series for the "zoomed" channel
                dpg.add_line_series([], [], label="Zoomed Channel",
                                    parent=self.y_axis_zoom, tag="zoomed_line")

    def channel_selection_callback(self, sender, app_data, user_data):
        """Called when user picks a channel from the combo."""
        self.selected_channel = int(app_data)

    def set_zoom_y_min(self, sender, app_data):
        self.zoom_y_min = app_data

    def set_zoom_y_max(self, sender, app_data):
        self.zoom_y_max = app_data

    def set_signal_separation(self, sender, app_data):
        self.signal_separation = app_data

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
        for ch in range(self.num_channels):
            pos = self.buffer_positions[ch]
            
            # Roll data so that index -1 corresponds to the newest sample
            rolled_y = np.roll(self.data_buffers[ch], -pos)
            rolled_x = np.roll(self.time_buffer, -pos)
            
            # Downsample
            ds_x = rolled_x[::ds_factor]
            ds_y = rolled_y[::ds_factor]
            
            # Apply vertical offset for each channel to avoid overlap
            offset = ch * 1000
            ds_y_offset = ds_y + offset
            
            # Update the line series for channel ch
            dpg.set_value(self.lines_all[ch], [ds_x.tolist(), ds_y_offset.tolist()])

        # -----------------------------
        # Update Zoomed Channel Plot
        # -----------------------------
        ch = self.selected_channel
        pos = self.buffer_positions[ch]
        
        rolled_y_ch = np.roll(self.data_buffers[ch], -pos)
        rolled_x_ch = np.roll(self.time_buffer, -pos)

        ds_x_ch = rolled_x_ch[::ds_factor]
        ds_y_ch = rolled_y_ch[::ds_factor]
        
        # Update the single "zoomed_line" series
        dpg.set_value("zoomed_line", [ds_x_ch.tolist(), ds_y_ch.tolist()])

        # Optionally set the zoomed plot Y-axis range for a closer look
        # For example, if data in each channel is in [0..4096]:
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
        channel, samples = data
        num_samples = len(samples)
        pos = self.buffer_positions[channel]

        end_pos = pos + num_samples
        if end_pos <= self.buffer_size:
            # Simple case: fits without wrap
            self.data_buffers[channel][pos:end_pos] = samples
        else:
            # Wrap around case
            first_part = self.buffer_size - pos
            second_part = num_samples - first_part
            self.data_buffers[channel][pos:] = samples[:first_part]
            self.data_buffers[channel][:second_part] = samples[first_part:]
        
        self.buffer_positions[channel] = (pos + num_samples) % self.buffer_size

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

def plot_synapse_data(stop: Event, data_queue: queue.Queue, num_channels: int):
    window_size_seconds = 3
    sample_rate_hz = 32000
    plotter = SynapsePlotter(num_channels, sample_rate_hz, window_size_seconds)
    plotter.start(stop, data_queue)
