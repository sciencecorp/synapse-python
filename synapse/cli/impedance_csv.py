"""Shared helpers for writing impedance-measurement CSV files.

Both the non-streaming (`synapsectl query`) and streaming (`--stream`) paths
emit the same CSV so downstream tooling can parse either identically:

    Peripheral: <name>
    Electrode ID,Magnitude (Ohms),Phase (degrees),Status
    <electrode_id>,<magnitude>,<phase>,<status>
    ...

`Status` is 1 for a successful measurement and 0 for a failed one.
"""

import csv

from synapse.api.device_pb2 import Peripheral

CSV_COLUMNS = ["Electrode ID", "Magnitude (Ohms)", "Phase (degrees)", "Status"]

STATUS_OK = 1
STATUS_FAILED = 0

# Force LF so the streaming (csv.writer) and non-streaming paths produce
# byte-identical files regardless of platform.
_LINE_TERMINATOR = "\n"


def resolve_peripheral_name(device, impedance_query) -> str:
    """Best-effort name of the peripheral the measurement ran on, for the CSV header.

    Prefers the ``peripheral_id`` named in the query (if the proto carries one);
    otherwise falls back to the device's broadband (recording) source, then the
    first peripheral. Returns "Unknown" if it can't be resolved.
    """
    info = device.info() if device is not None else None
    if not info or not info.peripherals:
        return "Unknown"

    # Command-range ids (e.g. 2 = "first broadband source") won't match a
    # concrete peripheral_id and fall through to the broadband lookup below.
    peripheral_id = getattr(impedance_query, "peripheral_id", 0)
    if peripheral_id:
        for p in info.peripherals:
            if p.peripheral_id == peripheral_id:
                return p.name

    for p in info.peripherals:
        if p.type == Peripheral.kBroadbandSource:
            return p.name

    return info.peripherals[0].name


def write_header(filename, peripheral_name):
    """Create (truncate) the CSV and write the peripheral line + column header."""
    with open(filename, "w", newline="") as f:
        f.write(f"Peripheral: {peripheral_name}{_LINE_TERMINATOR}")
        csv.writer(f, lineterminator=_LINE_TERMINATOR).writerow(CSV_COLUMNS)


def append_measurements(filename, measurements, status=STATUS_OK):
    """Append measurement rows to an existing CSV created by `write_header`."""
    with open(filename, "a", newline="") as f:
        writer = csv.writer(f, lineterminator=_LINE_TERMINATOR)
        for m in measurements:
            writer.writerow([m.electrode_id, m.magnitude, m.phase, status])
