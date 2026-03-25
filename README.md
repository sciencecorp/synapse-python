# Synapse Python client

This repo contains the Python client for the [Synapse API](https://science.xyz/technologies/synapse). More information about the API can be found in the [docs](https://science.xyz/docs/d/synapse/index).

Includes `synapsectl` command line utility:

    % synapsectl --help
    usage: synapsectl [-h] [--uri URI] [--version] [--verbose]
                    {discover,info,query,start,stop,configure,logs,read,plot,file,taps,deploy,build,settings,deploy-model} ...

    Synapse Device Manager

    options:
    -h, --help            show this help message and exit
    --uri URI, -u URI     The device identifier to connect to. Can either be the IP address or name
    --version             show program's version number and exit
    --verbose, -v         Enable verbose output

    Commands:
    {discover,info,query,start,stop,configure,logs,read,plot,file,taps,deploy,build,settings,deploy-model}
        discover            Discover Synapse devices on the network
        info                Get device information
        query               Execute a query on the device
        start               Start the device or an application
        stop                Stop the device or an application
        configure           Write a configuration to the device
        logs                Get logs from the device
        read                Read from a device's Broadband Tap and save to HDF5
        plot                Plot recorded synapse data
        file                File commands
        taps                Interact with taps on the network
        deploy              Deploy an application to a Synapse device
        build               Cross-compile and package an application into a .deb without deploying
        settings            Manage the persistent device settings
        deploy-model        Deploy a machine learning model to a Synapse device

As well as the base for a device implementation (`synapse/server`),

And a toy device `synapse-sim` for local development,

    % synapse-sim --help
    usage: synapse-sim [-h] --iface-ip IFACE_IP [--rpc-port RPC_PORT] [--discovery-port DISCOVERY_PORT]
                   [--discovery-addr DISCOVERY_ADDR] [--name NAME] [--serial SERIAL] [-v]

    Simple Synapse Device Simulator (Development)

    options:
    -h, --help            show this help message and exit
    --iface-ip IFACE_IP   IP of the network interface to use for streaming data
    --rpc-port RPC_PORT   Port to listen for RPC requests
    --discovery-port DISCOVERY_PORT
                            Port to listen for discovery requests
    --discovery-addr DISCOVERY_ADDR
                            UDP address to listen for discovery requests
    --name NAME           Device name
    --serial SERIAL       Device serial number
    -v, --verbose         Enable verbose output

For more information on deploy and build, visit [synapse-example-app](https://github.com/sciencecorp/synapse-example-app)

## A Note on Streaming

Synapse devices stream data to and from clients with UDP. To minimize packet loss, it is highly recommended that users increase their OS UDP buffer size.

### On Linux

Check the current UDP buffer size with:

```
% sysctl net.core.rmem_max # Recieve buffer
% sysctl net.core.wmem_max # Send buffer
```

To update the buffer size immediately:

```
% sudo sysctl -w net.core.rmem_max=10485760 # 10 MB
% sudo sysctl -w net.core.wmem_max=10485760 # 10 MB
```

Or make a persistent change by adding the following file:

```
% sudo touch /etc/sysctl.d/50-udp-buffersize.conf
# And add these lines:
net.core.rmem_max=10485760
net.core.wmem_max=10485760
```

then reboot for the changes to take effect.

### On MacOS

Check the current UDP buffer size:

```
% sysctl kern.ipc.maxsockbuf
```

To update the buffer size immediately:

```
sudo sysctl -w kern.ipc.maxsockbuf=10485760
```

This change will be lost when restarting your computer. To make the setting persistent across reboots, add the following to `/etc/sysctl.conf` (you must create the file if it does not already exist):

```
kern.ipc.maxsockbuf=10485760
```

## Writing clients

This library offers an idiomatic Python interpretation of the Synapse API:

```python
import synapse as syn

device = syn.Device("127.0.0.1:647")
info = device.info()

print("Device info: ", device.info())

channels = [
    syn.Channel(
        id=channel_num,
        electrode_id=channel_num * 2,
        reference_id=channel_num * 2 + 1
    ) for channel_num in range(32)
]

broadband = syn.BroadbandSource(
    peripheral_id=2,
    sample_rate_hz=30000,
    bit_width=12,
    gain=20.0,
    signal=syn.SignalConfig(
        electrode=syn.ElectrodeConfig(
            channels=channels,
            low_cutoff_hz=500.0,
            high_cutoff_hz=6000.0,
        )
    )
)

config = syn.Config()
config.add_node(broadband)

device.configure(config)
device.start()
```

## Implementing new Synapse devices

The `synapse.server` package can be used as the base for implementing Synapse-compatible interfaces for non-native systems by simply providing class implementations of the record and/or stimulation nodes (or any other relevant signal chain nodes).

For an example, see the [Blackrock Neurotech CerePlex driver](https://github.com/sciencecorp/synapse-cereplex-driver) implementation.

## Building

Dependencies:

    git submodule update --init
    pip install -r requirements.txt
    ./setup.sh all
    # or
    make all

To build and install in development mode:

    pip install -e .

To build and install a wheel:

    python -m build

    # and optionally install
    pip install dist/science_synapse-*.whl

## Development

If you want to catch linting errors before pushing, you can install a pre-commit hook.

```bash
pre-commit install

# To run manually
pre-commit run
```

## Plotting Offline

After recording data to a file, you can generate plots to visualize your data. Using the CLI, you can run:

```
synapsectl plot --dir <path to directory containing .dat and .json>
```

## Model Deployment

Deploy machine learning models to Synapse devices.

### Prerequisites

1. **Docker** — required for model conversion
2. **QAIRT SDK v2.34** (Qualcomm AI Runtime) — required for model conversion

#### Installing the QAIRT SDK

1. Create a free account at [softwarecenter.qualcomm.com](https://softwarecenter.qualcomm.com/) (no paid license required)
2. Download **Qualcomm Software Center** (Linux `.deb`) and **Qualcomm AI Runtime v2.34** (Linux `.qik`) from the website
3. Install both:
   ```bash
   # Install Qualcomm Software Center (includes the qik package manager)
   sudo dpkg -i QualcommSoftwareCenter*.deb

   # Install the QAIRT SDK
   sudo /opt/qcom/softwarecenter/bin/qik/qik INSTALL "/path/to/Qualcomm_AI_Runtime_SDK.2.34.0.250424.Linux-AnyCPU.qik"
   ```
4. The SDK installs to `/opt/qcom/aistack/qairt/2.34.0.250424`. You'll pass this path as `--snpe-root` when deploying models.

### Quick Start — Deploy a Float Model (CPU)

The simplest path — no calibration data needed, runs on CPU:

```bash
synapsectl deploy-model model.onnx \
  --name my_model \
  --snpe-root /opt/qcom/aistack/qairt/2.34.0.250424 \
  -u <device-ip>
```

### Deploy a Quantized Model (DSP)

For production performance, quantize the model to INT8 for DSP inference. This requires **calibration data** — a small set of example inputs that represent what the model will see in real use.

#### What is calibration data and why do I need it?

Quantization converts your model from 32-bit floats to 8-bit integers, making it ~4x smaller and much faster on the DSP. But to do this well, the quantizer needs to see what typical input values look like so it can choose the right scale for each layer. Bad calibration data leads to accuracy loss.

**Good calibration data** is a handful of real (or realistic) inputs from your application. For example:
- If your model processes neural signals, use 10-50 snippets of actual recorded neural data
- If your model processes audio, use 10-50 clips of real audio
- If you don't have real data yet, synthetic data that matches the expected distribution is acceptable

Ideally, use at least **1000 representative samples** for best accuracy. Fewer samples (50-100) can work for initial testing, but more data gives the quantizer a better picture of your model's value ranges.

#### Step 1: Create calibration `.raw` files

Each `.raw` file is a flat binary dump of float32 values matching your model's input shape. Create them with numpy:

```python
import numpy as np

# Example: model expects input shape [1, 1920]
# Load your real data here — these should be actual inputs, not random noise
for i, sample_data in enumerate(my_real_samples[:20]):
    # sample_data should be a numpy array with shape matching your model input
    sample_data.astype(np.float32).tofile(f"sample_{i:03d}.raw")
```

If you don't have real data yet, you can use synthetic data to get started (accuracy may be lower):

```python
import numpy as np

for i in range(20):
    sample = np.random.randn(1, 1920).astype(np.float32)
    sample.tofile(f"sample_{i:03d}.raw")
```

#### Step 2: Create an input list file

Create a text file called `input_list.txt` listing your `.raw` files, one per line. Put this file in the same directory as the `.raw` files.

```
sample_000.raw
sample_001.raw
sample_002.raw
sample_003.raw
sample_004.raw
sample_005.raw
sample_006.raw
sample_007.raw
sample_008.raw
sample_009.raw
```

#### Step 3: Deploy with quantization

```bash
synapsectl deploy-model model.onnx \
  --name my_model \
  --quantize --input-list input_list.txt \
  --snpe-root /opt/qcom/aistack/qairt/2.34.0.250424 \
  -u <device-ip>
```

### Use in Your C++ App

```cpp
#include <synapse-app-sdk/inference/model.hpp>

// Loads models/<name>.dlc from the device model directory
auto model = synapse::create_model("my_model");

if (model && model->is_ready()) {
    auto result = model->infer(input_data);
    // result.success, result.outputs, result.inference_time_us
}
```

The runtime is selected automatically: quantized models run on the DSP, float models run on CPU. You can also specify a runtime explicitly:

```cpp
auto model = synapse::create_model("my_model", synapse::InferenceRuntime::kDsp);
```
