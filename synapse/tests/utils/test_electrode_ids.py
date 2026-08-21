from synapse.api.channel_pb2 import Channel, ChannelRange, ChannelType
from synapse.api.datatype_pb2 import BroadbandFrame
from synapse.api.device_pb2 import DeviceInfo, Peripheral
from synapse.api.node_pb2 import NodeType
from synapse.utils.electrode_ids import (
    GPIO_CHANNEL_ID_OFFSET,
    build_channel_to_electrode_map,
    derive_electrode_row_ids,
)


def make_frame(num_rows, ranges=None):
    frame = BroadbandFrame(frame_data=list(range(num_rows)))
    for channel_range in ranges or []:
        frame.channel_ranges.append(channel_range)
    return frame


def electrode_range(count, channel_ids=None):
    return ChannelRange(
        type=ChannelType.ELECTRODE, count=count, channel_ids=channel_ids or []
    )


def make_device_info(channels, peripheral=None):
    info = DeviceInfo()
    if peripheral is not None:
        info.peripherals.append(peripheral)
    node = info.configuration.nodes.add()
    node.type = NodeType.kBroadbandSource
    node.broadband_source.peripheral_id = (
        peripheral.peripheral_id if peripheral is not None else 0
    )
    node.broadband_source.signal.electrode.channels.extend(channels)
    return info


# Horacio's report: 5 channels referenced to ground, configured out of ascending
# order, two of them on non-functional electrodes.
HORACIO_ELECTRODES = [6, 16, 10, 14, 20]
HORACIO_CHANNELS = [
    Channel(id=i, electrode_id=electrode_id, reference_id=520)
    for i, electrode_id in enumerate(HORACIO_ELECTRODES)
]


def test_returns_none_for_an_empty_frame():
    assert derive_electrode_row_ids(make_frame(0)) is None


def test_maps_logical_channel_ids_to_physical_electrode_ids():
    frame = make_frame(5, [electrode_range(5, [0, 1, 2, 3, 4])])
    rows = derive_electrode_row_ids(frame, {0: 6, 1: 16, 2: 10, 3: 14, 4: 20})

    assert rows.ids == HORACIO_ELECTRODES
    assert rows.channel_ids == [0, 1, 2, 3, 4]
    assert rows.source == "electrode_map"
    assert rows.warnings == []


def test_preserves_the_configured_electrode_order():
    """The configured order is the recorded order — no ascending re-sort."""
    frame = make_frame(5, [electrode_range(5, [0, 1, 2, 3, 4])])
    rows = derive_electrode_row_ids(
        frame, build_channel_to_electrode_map(make_device_info(HORACIO_CHANNELS))
    )

    assert rows.ids == [6, 16, 10, 14, 20]
    assert rows.ids != sorted(rows.ids)


def test_falls_back_to_logical_ids_without_a_map():
    frame = make_frame(3, [electrode_range(3, [7, 8, 9])])
    rows = derive_electrode_row_ids(frame)

    assert rows.ids == [7, 8, 9]
    assert rows.source == "channel_ranges"
    assert any("No channel-to-electrode map" in w for w in rows.warnings)


def test_falls_back_to_logical_ids_when_the_map_is_incomplete():
    frame = make_frame(3, [electrode_range(3, [0, 1, 2])])
    rows = derive_electrode_row_ids(frame, {0: 6, 1: 16})

    assert rows.ids == [0, 1, 2]
    assert rows.source == "channel_ranges"
    assert any("does not cover every streamed channel" in w for w in rows.warnings)


def test_rekeys_gpio_rows_and_preserves_the_row_count():
    frame = make_frame(
        4,
        [
            electrode_range(2, [0, 1]),
            ChannelRange(type=ChannelType.GPIO, count=2, channel_ids=[1, 3]),
        ],
    )
    rows = derive_electrode_row_ids(frame, {0: 6, 1: 16})

    assert rows.ids == [6, 16, GPIO_CHANNEL_ID_OFFSET + 1, GPIO_CHANNEL_ID_OFFSET + 3]
    assert rows.types == [
        ChannelType.ELECTRODE,
        ChannelType.ELECTRODE,
        ChannelType.GPIO,
        ChannelType.GPIO,
    ]
    assert len(rows.ids) == len(frame.frame_data)
    assert rows.source == "electrode_map"


def test_uses_contiguous_ids_when_a_range_omits_channel_ids():
    """Pre-fix Nixel512 firmware sends a bare count."""
    frame = make_frame(3, [electrode_range(3)])
    rows = derive_electrode_row_ids(frame)

    assert rows.ids == [0, 1, 2]
    assert rows.source == "positional"
    assert any("omit channel_ids" in w for w in rows.warnings)


def test_resolves_electrodes_for_a_contiguous_range_when_mapped():
    frame = make_frame(3, [electrode_range(3)])
    rows = derive_electrode_row_ids(frame, {0: 6, 1: 16, 2: 10})

    assert rows.ids == [6, 16, 10]
    assert rows.source == "electrode_map"


def test_falls_back_to_positional_ids_without_channel_ranges():
    rows = derive_electrode_row_ids(make_frame(3), {0: 6, 1: 16, 2: 10})

    assert rows.channel_ids == [0, 1, 2]
    assert rows.ids == [6, 16, 10]
    assert any("no channel_ranges" in w for w in rows.warnings)


def test_falls_back_to_positional_ids_when_ranges_disagree_with_frame_size():
    frame = make_frame(3, [electrode_range(5, [0, 1, 2, 3, 4])])
    rows = derive_electrode_row_ids(frame)

    assert rows.channel_ids == [0, 1, 2]
    assert rows.source == "positional"
    assert any("describe 5 channels" in w for w in rows.warnings)


def test_builds_the_map_from_the_device_configuration():
    assert build_channel_to_electrode_map(make_device_info(HORACIO_CHANNELS)) == {
        0: 6,
        1: 16,
        2: 10,
        3: 14,
        4: 20,
    }


def test_skips_peripherals_with_placeholder_electrode_ids():
    virtual = Peripheral(
        name="SciFi Virtual Recording Peripheral",
        vendor="Science Corporation",
        peripheral_id=3,
    )
    channels = [Channel(id=i, electrode_id=2 * i) for i in range(3)]

    assert build_channel_to_electrode_map(make_device_info(channels, virtual)) == {}


def test_builds_an_empty_map_for_a_missing_device_info():
    assert build_channel_to_electrode_map(None) == {}
