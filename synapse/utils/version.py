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


def decode_firmware_version(v: int) -> str:
    """Decode a DeviceInfo.firmware_version uint32 into e.g. "2.5.0".

    Encoding (headstage CMakeLists.txt, from ops/release/manifest.toml):
      bits [31:24] device (1 = SciFi1, 2 = SciFi2)
      bits [23:16] major, [15:8] minor, [7:0] patch

    Older firmware put a git hash in this field; anything without a known
    device byte is shown as that hex hash.
    """
    # ponytail: an old git hash whose top byte happens to be 0x01/0x02 decodes wrongly; unavoidable without a proto change.
    if (v >> 24) & 0xFF not in (1, 2):
        return f"{v:x}"
    return f"{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"
