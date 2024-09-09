from synapse.device import Device
from synapse.config import Config
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.stream_out import StreamOut
from synapse.channel import Channel

def read(uri):
    # Create device class to handle communication with the device
    dev = Device(uri)

    # Create a signal chain configuration; adding nodes and then connecting their outputs to inputs
    config = Config()
    e_record = ElectricalBroadband(
        peripheral_id=0,
        channels=[Channel(channel_id=i) for i in range(10)],
        bit_width=4,
        sample_rate=30000
    )
    stream_out = StreamOut()
    config.add_node(e_record)
    config.add_node(stream_out)
    config.connect(e_record, stream_out)

    # Configure the device with the signal chain configuration
    if not dev.configure(config):
      print("Failed to configure device")
      return

    # Get device info and print it
    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return
    
    print("Configured device:")
    print(info)

    # Start the device
    if not dev.start():
        print("Failed to start device")
        return
    
    # Read data from the stream_out node
    try:
        while True:
            data = stream_out.read()
            if data:
                value = int.from_bytes(data, "big")
                print(value)
    except KeyboardInterrupt:
        pass

    # Stop the device
    if not dev.stop():
        print("Failed to stop device")
        return

if __name__ == "__main__":
    uri = "localhost:647"
    read(uri)