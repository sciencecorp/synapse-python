import synapse as syn

if __name__ == "__main__":
    device = syn.Device("127.0.0.1:647")
    info = device.info()
    assert info is not None, "Couldn't get device info"
    print(info)

    stream_out = syn.StreamOut(label="my broadband", multicast_group="239.0.0.1")
    broadband = syn.BroadbandSource(
        peripheral_id=2,
        sample_rate_hz=30000,
        bit_width=12,
        gain=20.0,
        signal=syn.Signal(
            channels=[syn.Channel(id=c, electrode_id=c * 2, reference_id=c * 2 + 1) for c in range(32)],
            low_cutoff_hz=500.0,
            high_cutoff_hz=6000.0,
        )
    )

    config = syn.Config()
    config.add_node(stream_out)
    config.add_node(broadband)
    config.connect(broadband, stream_out)

    device.configure(config)
    device.start()
    
    