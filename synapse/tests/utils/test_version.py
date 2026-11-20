from synapse.utils.version import decode_firmware_version


def test_decode_firmware_version():
    assert decode_firmware_version(0x02020500) == "2.5.0"
    assert decode_firmware_version(0x01010A00) == "1.10.0"
    # Older firmware sent a git hash; unknown device byte falls back to hex.
    assert decode_firmware_version(0x598A7FC2) == "598a7fc2"
