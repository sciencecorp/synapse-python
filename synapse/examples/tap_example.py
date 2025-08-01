import synapse as syn
import sys
import time

from synapse.client.taps import Tap

SIMULATED_PERIPHERAL_ID = 100

if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:647"
    device = syn.Device(uri)
    info = device.info()
    if info is None:
        print("Couldn't get device info")
        sys.exit(1)

    print("Device info:")
    print(info)

    channels = [
        syn.Channel(
            id=channel_num,
            electrode_id=channel_num * 2,
            reference_id=channel_num * 2 + 1,
        )
        for channel_num in range(32)
    ]

    broadband = syn.BroadbandSource(
        # Use the simulated peripheral (100), or replace with your own
        peripheral_id=SIMULATED_PERIPHERAL_ID,
        sample_rate_hz=30000,
        bit_width=12,
        gain=20.0,
        signal=syn.SignalConfig(
            electrode=syn.ElectrodeConfig(
                channels=channels,
                low_cutoff_hz=500.0,
                high_cutoff_hz=6000.0,
            )
        ),
    )

    config = syn.Config()
    config.add_node(broadband)

    device.configure(config)

    # export the config to a json file for using with CLI
    # from google.protobuf.json_format import MessageToJson
    # with open("device_config.json", "w") as f:
    #     f.write(MessageToJson(config.to_proto()))
    # print("Config written to device_config.json")

    device.start()

    info = device.info()
    if info is None:
        print("Couldn't get device info")
        sys.exit(1)
    print("Configured device info:")
    print(info)

    # stream with tap api
    tap_client = Tap(uri)
    tap_client.connect("broadband_source_sim")

    should_run = True
    total_bytes_read = 0
    start_time = time.time()
    last_update_time = start_time
    update_interval_sec = 1
    while should_run:
        try:
            # Wait for data
            syn_data = tap_client.read()
            bytes_read = len(syn_data)
            if syn_data is None or bytes_read == 0:
                print("Failed to read data from node")
                continue
            # Do something with the data
            total_bytes_read += bytes_read

            current_time = time.time()
            if (current_time - last_update_time) >= update_interval_sec:
                sys.stdout.write("\r")
                sys.stdout.write(
                    f"{total_bytes_read} bytes in {time.time() - start_time:.2f} sec"
                )
                last_update_time = current_time

            if current_time - start_time > 5:
                should_run = False

        except KeyboardInterrupt:
            print("Keyboard interrupt detected, stopping")
            should_run = False

    print("Stopping device")
    device.stop()

