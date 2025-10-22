import os
import csv
import subprocess
from pathlib import Path
import numpy as np
import h5py
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

def validate_hdf5_structure(filename, console):
    """Validate that the HDF5 file matches the company-enforced structure."""
    try:
        with h5py.File(filename, 'r') as f:
            # Check root attributes
            required_root_attrs = ['lsb_uv', 'sample_rate_hz', 'session_description', 'session_start_time']
            for attr in required_root_attrs:
                if attr not in f.attrs:
                    console.print(f"[bold red]Missing root attribute: {attr}[/bold red]")
                    return False
            
            # Check acquisition group and datasets
            if 'acquisition' not in f:
                console.print("[bold red]Missing 'acquisition' group[/bold red]")
                return False
            
            acq = f['acquisition']
            required_datasets = [
                'ElectricalSeries',
                'channel_range_count',
                'channel_range_start',
                'channel_range_type',
                'sequence_number',
                'timestamp_ns',
                'unix_timestamp_ns'
            ]
            
            for dataset in required_datasets:
                if dataset not in acq:
                    console.print(f"[bold red]Missing dataset in acquisition: {dataset}[/bold red]")
                    return False
            
            # Check general/device structure
            if 'general' not in f or 'device' not in f['general']:
                console.print("[bold red]Missing 'general/device' group[/bold red]")
                return False
            
            if 'device_type' not in f['general']['device'].attrs:
                console.print("[bold red]Missing 'device_type' attribute in general/device[/bold red]")
                return False
            
            # Check general/extracellular_ephys/electrodes
            if ('general' not in f or 
                'extracellular_ephys' not in f['general'] or 
                'electrodes' not in f['general']['extracellular_ephys']):
                console.print("[bold red]Missing 'general/extracellular_ephys/electrodes' structure[/bold red]")
                return False
            
            if 'id' not in f['general']['extracellular_ephys']['electrodes']:
                console.print("[bold red]Missing 'id' dataset in electrodes[/bold red]")
                return False
            
            console.print("[green]✓ HDF5 structure validation passed[/green]")
            return True
            
    except Exception as e:
        console.print(f"[bold red]Error validating HDF5 file: {e}[/bold red]")
        return False

def compute_spike_statistics(filename, console, num_chunks=128, threshold_std=3.0):
    """
    Compute aggregate spike statistics across all channels.
    Returns total spike distribution across time chunks with squaring transformation.
    """
    console.print(f"\n[cyan]Computing spike distribution with {num_chunks} time chunks...[/cyan]")
    
    try:
        with h5py.File(filename, 'r') as f:
            # Get the electrical series data
            electrical_series = f['acquisition']['ElectricalSeries']
            channel_ids = f['general']['extracellular_ephys']['electrodes']['id'][:]
            num_channels = len(channel_ids)
            total_samples = electrical_series.shape[0]
            
            console.print(f"[dim]Total samples: {total_samples:,}[/dim]")
            console.print(f"[dim]Number of channels: {num_channels}[/dim]")
            console.print(f"[dim]Data shape: {electrical_series.shape}[/dim]")
            
            # Determine data layout
            if len(electrical_series.shape) == 1:
                # Data is 1D - likely interleaved channels
                console.print("[yellow]Warning: 1D data detected. Assuming interleaved channel format.[/yellow]")
                samples_per_channel = total_samples // num_channels
                is_interleaved = True
            else:
                # Data is 2D [samples, channels] or [channels, samples]
                is_interleaved = False
                if electrical_series.shape[1] == num_channels:
                    samples_per_channel = electrical_series.shape[0]
                    channel_axis = 1
                else:
                    samples_per_channel = electrical_series.shape[1]
                    channel_axis = 0
            
            samples_per_chunk = samples_per_channel // num_chunks
            
            # Less aggressive subsampling - read ~10% of each chunk
            subsample_size = max(5000, samples_per_chunk // 10)
            
            console.print(f"[dim]Samples per channel: {samples_per_channel:,}[/dim]")
            console.print(f"[dim]Samples per chunk: {samples_per_chunk:,}[/dim]")
            console.print(f"[dim]Reading ~{subsample_size} samples per chunk for estimation[/dim]")
            
            # Initialize aggregate spike counts across all channels
            aggregate_spike_counts = np.zeros(num_chunks, dtype=np.int64)
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=console
            ) as progress:
                task = progress.add_task(f"Processing {num_channels} channels...", total=num_channels)
                
                for ch_idx, ch_id in enumerate(channel_ids):
                    for chunk_idx in range(num_chunks):
                        chunk_start = chunk_idx * samples_per_chunk
                        chunk_end = min((chunk_idx + 1) * samples_per_chunk, samples_per_channel)
                        
                        # Read a representative sample from the middle of this chunk
                        sample_start = chunk_start + samples_per_chunk // 2 - subsample_size // 2
                        sample_end = sample_start + subsample_size
                        
                        # Ensure we don't go out of bounds
                        sample_start = max(chunk_start, min(sample_start, chunk_end - subsample_size))
                        sample_end = min(chunk_end, sample_start + subsample_size)
                        
                        try:
                            # Read data efficiently based on layout
                            if is_interleaved:
                                # For 1D interleaved: read block and extract channel
                                start_idx = sample_start * num_channels + ch_idx
                                channel_data = electrical_series[start_idx:sample_end * num_channels:num_channels]
                            else:
                                # For 2D data: slice appropriately
                                if channel_axis == 1:
                                    channel_data = electrical_series[sample_start:sample_end, ch_idx]
                                else:
                                    channel_data = electrical_series[ch_idx, sample_start:sample_end]
                            
                            # Convert to float for processing
                            channel_data = channel_data.astype(np.float32)
                            
                            # Quick preprocessing
                            channel_data -= np.mean(channel_data)
                            std = np.std(channel_data)
                            
                            if std > 0:
                                threshold = threshold_std * std
                                # Count spikes in this sample
                                spike_count = np.sum(np.abs(channel_data) > threshold)
                                # Extrapolate to full chunk
                                scaling_factor = samples_per_chunk / subsample_size
                                aggregate_spike_counts[chunk_idx] += int(spike_count * scaling_factor)
                            
                        except Exception as e:
                            console.print(f"[yellow]Warning: Error reading chunk {chunk_idx} for channel {ch_id}: {e}[/yellow]")
                    
                    progress.update(task, advance=1)
            
            # Normalize by total spike count to get distribution
            total_spikes = np.sum(aggregate_spike_counts)
            if total_spikes > 0:
                normalized_distribution = aggregate_spike_counts / total_spikes
            else:
                normalized_distribution = aggregate_spike_counts.astype(np.float64)
            
            console.print(f"[dim]Total spikes detected (approx): {total_spikes:,}[/dim]")
            console.print(f"[dim]Distribution range before transform: [{normalized_distribution.min():.6f}, {normalized_distribution.max():.6f}][/dim]")
            
            # Apply squaring transformation to emphasize differences
            squared_distribution = normalized_distribution ** 2
            
            # Renormalize after squaring
            squared_sum = np.sum(squared_distribution)
            if squared_sum > 0:
                final_distribution = (squared_distribution / squared_sum).tolist()
            else:
                final_distribution = squared_distribution.tolist()
            
            console.print(f"[dim]Distribution range after transform: [{min(final_distribution):.6f}, {max(final_distribution):.6f}][/dim]")
            console.print("[green]✓ Spike distribution computed with squaring transformation[/green]")
            
            return final_distribution
            
    except Exception as e:
        console.print(f"[bold red]Error computing spike statistics: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return None

def upload(args):
    console = Console()

    if not args.filename:
        console.print("[bold red]Error: No filename specified[/bold red]")
        return
    
    # Check file extension
    file_path = Path(args.filename)
    if file_path.suffix.lower() not in ['.hdf5', '.h5']:
        console.print(f"[bold red]Error: File must be .hdf5 or .h5 format (got {file_path.suffix})[/bold red]")
        return
    
    if not os.path.exists(args.filename):
        console.print(f"[bold red]Error: File '{args.filename}' does not exist[/bold red]")
        return

    # Validate HDF5 structure
    console.print(f"[cyan]Validating HDF5 structure...[/cyan]")
    if not validate_hdf5_structure(args.filename, console):
        console.print("[bold red]HDF5 validation failed. Upload aborted.[/bold red]")
        return

    # Compute spike statistics
    spike_distribution = compute_spike_statistics(args.filename, console)
    csv_path = None
    
    if spike_distribution is None:
        console.print("[bold yellow]Warning: Could not compute spike statistics[/bold yellow]")
    else:
        # Write distribution to CSV file (single row with 128 values)
        csv_path = file_path.with_suffix(file_path.suffix + '.csv')
        try:
            with open(csv_path, 'w', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(spike_distribution)
            console.print(f"[green]✓ Spike distribution written to {csv_path}[/green]")
        except Exception as e:
            console.print(f"[bold red]Error writing CSV file: {e}[/bold red]")
            csv_path = None

    file_size = os.path.getsize(args.filename)
    file_size_mb = file_size / (1024 * 1024)

    uri = args.uri
    remote_host = f"scifi@{uri}"
    remote_dir = "~/replay"
    remote_path = f"{remote_host}:{remote_dir}"
    mkdir_command = ["ssh", remote_host, f"mkdir -p {remote_dir}"]
    
    console.print(f"\n[cyan]Uploading file:[/cyan] {args.filename}")
    console.print(f"[cyan]File size:[/cyan] {file_size_mb:.2f} MB")
    console.print(f"[cyan]Destination:[/cyan] {remote_path}")

    try:
        # Ensure ~/replay directory exists
        console.print(f"\n[cyan]Ensuring directory exists: {remote_dir}[/cyan]")
        subprocess.run(mkdir_command, check=True, capture_output=True, text=True)
        console.print(f"[green]✓ Directory ready[/green]")

        # Copy over the HDF5 file
        console.print(f"\n[cyan]Uploading {args.filename} to {remote_path}...[/cyan]")
        console.print("[dim]You may be prompted for a password[/dim]\n")
        scp_command = ["scp", args.filename, remote_path]
        subprocess.run(scp_command, check=True)
        console.print(f"[bold green]✓ Successfully uploaded {args.filename}[/bold green]")
        
        # Upload CSV file if it exists
        if csv_path and os.path.exists(csv_path):
            console.print(f"\n[cyan]Uploading {csv_path.name} to {remote_path}...[/cyan]")
            csv_scp_command = ["scp", str(csv_path), remote_path]
            subprocess.run(csv_scp_command, check=True)
            console.print(f"[bold green]✓ Successfully uploaded {csv_path.name}[/bold green]")
        
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red]✗ Upload failed[/bold red]")

def add_commands(subparsers):
    upload_parser = subparsers.add_parser("upload", help="Upload HDF5 recordings to your Synapse device")
    upload_parser.add_argument("filename", type=str, help="Path to the HDF5 file (.hdf5 or .h5) to upload")
    upload_parser.set_defaults(func=upload)