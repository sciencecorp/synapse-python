def decode_synapse_version(v: int) -> str:
    """Decode a Synapse API version uint32 into a "major.minor.patch" string.

    Encoding (see synapse-api device.proto, DeviceInfo.synapse_version):
      bits [31:24] major (0-255)
      bits [23:16] minor (0-255)
      bits [15:0]  patch (0-65535)
    """
    major = (v >> 24) & 0xFF
    minor = (v >> 16) & 0xFF
    patch = v & 0xFFFF
    return f"{major}.{minor}.{patch}"
