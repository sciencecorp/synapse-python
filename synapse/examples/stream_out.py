import synapse as syn

if __name__ == "__main__":
    device = syn.Device("127.0.0.1:647")
    info = device.info()
    assert info is not None, "Couldn't get device info"
    print(info)

    stream_out = syn.StreamOut(label="my broadband", multicast_group="239.0.0.1")
    e_broadband = syn.ElectricalBroadband(
        peripheral_id=2,
        channels=[syn.Channel(id=c, electrode_id=c * 2, reference_id=c * 2 + 1) for c in range(32)],
        sample_rate=30000,
        bit_width=12,
        gain=20.0,
        low_cutoff_hz=500.0,
        high_cutoff_hz=6000.0,
    )

    config = syn.Config()
    config.add_node(stream_out)
    config.add_node(e_broadband)
    config.connect(e_broadband, stream_out)

    device.configure(config)
    device.start()
    
    