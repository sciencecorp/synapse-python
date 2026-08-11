"""Per-row channel identity for broadband recordings.

The broadband stream carries one entry per channel per frame and identifies
those entries only by *logical* channel id — the 0-based index of the channel
within the BroadbandSource configuration. The physical electrode behind each
logical channel lives in the device configuration, not in the stream, so
recording the stream alone loses the mapping from row to electrode.

This module reconstructs that identity: `build_channel_to_electrode_map` reads
the logical -> physical mapping out of a DeviceInfo, and
`derive_electrode_row_ids` combines it with a frame's `channel_ranges` to
produce one id per frame_data entry.

Mirrors `deriveElectrodeRowIds` in nexus-desktop
(src/ipc/main/hdf5-writer.ts); the two write the same HDF5 layout and must stay
in sync.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from synapse.api.channel_pb2 import ChannelType
from synapse.api.node_pb2 import NodeType

# The device emits GPIO channels in the broadband stream keyed by their GPIO
# line index, which collides with the contiguous electrode channel ids —
# electrode channel 1 and GPIO line 1 are both "1". GPIO rows are re-keyed into
# this high namespace so every id in the electrode table is unique. Mirrors
# GPIO_CHANNEL_ID_OFFSET in nexus-desktop.
GPIO_CHANNEL_ID_OFFSET = 1_000_000

# Peripherals whose configuration carries placeholder electrode ids rather than
# real ones. The virtual recording peripheral generates synthetic data and
# derives electrode_id = 2 * id, so there is no physical electrode behind those
# ids and remapping the stream through them only corrupts the labels (0, 1, 2 ->
# 0, 2, 4). Matched on the (name, vendor) the firmware reports.
_PLACEHOLDER_ELECTRODE_PERIPHERALS = frozenset(
    {("SciFi Virtual Recording Peripheral", "Science Corporation")}
)

# Where the per-row ids in general/extracellular_ephys/electrodes/id came from.
ID_SOURCE_ELECTRODE_MAP = "electrode_map"  # real physical electrode ids
ID_SOURCE_CHANNEL_RANGES = "channel_ranges"  # device-reported logical channel ids
ID_SOURCE_POSITIONAL = "positional"  # row index; no identity at all (legacy)


@dataclass
class ElectrodeRowIds:
    """Per-frame_data-entry channel identity.

    Every list has exactly len(frame.frame_data) entries, so the length of
    electrodes/id keeps matching the number of entries per frame in
    ElectricalSeries (which may include non-electrode GPIO channels).
    """

    ids: List[int]
    """One id per frame_data entry — what goes into electrodes/id."""

    channel_ids: List[int]
    """Logical stream channel id per frame_data entry."""

    types: List[int]
    """synapse.ChannelType per frame_data entry."""

    source: str
    """One of the ID_SOURCE_* constants above."""

    warnings: List[str]
    """Set when identity had to degrade; the caller reports these."""


def build_channel_to_electrode_map(device_info) -> Dict[int, int]:
    """Build the logical channel id -> physical electrode id lookup.

    Reads every BroadbandSource node's configured channels, each of which
    carries both an `id` (the logical/stream id) and an `electrode_id` (the
    real electrode). Nodes fed by a placeholder-electrode peripheral are
    skipped so their channels stay unmapped and fall back to logical ids.
    """
    mapping: Dict[int, int] = {}
    if device_info is None:
        return mapping

    peripherals_by_id = {
        peripheral.peripheral_id: peripheral
        for peripheral in device_info.peripherals
    }

    for node in device_info.configuration.nodes:
        if node.type != NodeType.kBroadbandSource:
            continue
        peripheral = peripherals_by_id.get(node.broadband_source.peripheral_id)
        if peripheral is not None and (
            peripheral.name,
            peripheral.vendor,
        ) in _PLACEHOLDER_ELECTRODE_PERIPHERALS:
            continue
        for channel in node.broadband_source.signal.electrode.channels:
            mapping[channel.id] = channel.electrode_id

    return mapping


def derive_electrode_row_ids(
    frame, channel_to_electrode: Optional[Dict[int, int]] = None
) -> Optional[ElectrodeRowIds]:
    """Derive per-row channel identity for a BroadbandFrame.

    The frame describes its own layout in `channel_ranges`: each range gives a
    ChannelType, a count, and — when the peripheral populates it — the logical
    channel ids in frame order. Ranges that omit channel_ids are contiguous,
    with ids running in frame order.

    Returns None for an empty frame. Otherwise the result always has one entry
    per frame_data entry, degrading through the ID_SOURCE_* levels (and
    recording a warning) whenever real identity isn't available.
    """
    num_rows = len(frame.frame_data) if frame is not None else 0
    if num_rows <= 0:
        return None

    channel_ids = [0] * num_rows
    types = [ChannelType.ELECTRODE] * num_rows
    warnings: List[str] = []
    has_explicit_ids = False
    used_ranges = False

    ranges = list(frame.channel_ranges)
    if ranges:
        declared = sum(r.count for r in ranges)
        if declared != num_rows:
            warnings.append(
                f"BroadbandFrame.channel_ranges describe {declared} channels but the "
                f"frame has {num_rows} entries; falling back to positional channel ids."
            )
        else:
            row = 0
            next_contiguous_id = 0
            for channel_range in ranges:
                explicit = list(channel_range.channel_ids)
                for i in range(channel_range.count):
                    if i < len(explicit):
                        channel_ids[row] = explicit[i]
                        has_explicit_ids = True
                    else:
                        # Contiguous range: ids run in frame order from where
                        # the previous range left off.
                        channel_ids[row] = next_contiguous_id
                        next_contiguous_id += 1
                    types[row] = channel_range.type
                    row += 1
            used_ranges = True
    else:
        warnings.append(
            "BroadbandFrame carries no channel_ranges; falling back to positional "
            "channel ids (all entries assumed to be electrodes)."
        )

    if not used_ranges:
        channel_ids = list(range(num_rows))
        types = [ChannelType.ELECTRODE] * num_rows
    elif not has_explicit_ids:
        warnings.append(
            "BroadbandFrame.channel_ranges omit channel_ids; channel identity falls "
            "back to positional ordering within each range."
        )

    # Resolve logical channel ids to physical electrode ids, but only when
    # *every* electrode row resolves: a partial map would mix the two id spaces
    # in one dataset, which is worse than an honest logical-id dataset.
    electrode_rows = [i for i in range(num_rows) if types[i] != ChannelType.GPIO]
    all_mapped = bool(channel_to_electrode) and all(
        channel_ids[i] in channel_to_electrode for i in electrode_rows
    )
    use_map = all_mapped and len(electrode_rows) > 0

    ids: List[int] = []
    for i in range(num_rows):
        if types[i] == ChannelType.GPIO:
            ids.append(GPIO_CHANNEL_ID_OFFSET + channel_ids[i])
        elif use_map:
            ids.append(channel_to_electrode[channel_ids[i]])
        else:
            ids.append(channel_ids[i])

    if not use_map and electrode_rows:
        if channel_to_electrode:
            warnings.append(
                "Channel-to-electrode map does not cover every streamed channel; "
                "writing logical channel ids instead of physical electrode ids."
            )
        else:
            warnings.append(
                "No channel-to-electrode map supplied; writing logical channel ids "
                "instead of physical electrode ids."
            )

    if use_map:
        source = ID_SOURCE_ELECTRODE_MAP
    elif has_explicit_ids:
        source = ID_SOURCE_CHANNEL_RANGES
    else:
        source = ID_SOURCE_POSITIONAL

    return ElectrodeRowIds(
        ids=ids,
        channel_ids=channel_ids,
        types=[int(t) for t in types],
        source=source,
        warnings=warnings,
    )
