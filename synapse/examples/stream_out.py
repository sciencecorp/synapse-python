import synapse as syn
import sys

if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:647"
    device = syn.Device(uri)
    info = device.info()
    assert info is not None, "Couldn't get device info"

    print("Device info:")
    print(info)

    stream_out = syn.StreamOut(label="my broadband", multicast_group="224.0.0.1")
    
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
    config.add_node(stream_out)
    config.add_node(broadband)
    config.connect(broadband, stream_out)

    device.configure(config)
    device.start()

    info = device.info()
    assert info is not None, "Couldn't get device info"
    print("Configured device info:")
    print(info)
    
    device.stop()
