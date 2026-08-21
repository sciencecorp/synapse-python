import h5py

from synapse.api.channel_pb2 import ChannelRange, ChannelType
from synapse.api.datatype_pb2 import BroadbandFrame
from synapse.cli.streaming import BroadbandFrameWriter
from synapse.utils.electrode_ids import (
    GPIO_CHANNEL_ID_OFFSET,
    derive_electrode_row_ids,
)


def write_attributes(tmp_path, frame, channel_to_electrode=None):
    """Run set_attributes for a frame and hand back the resulting file."""
    rows = derive_electrode_row_ids(frame, channel_to_electrode)
    writer = BroadbandFrameWriter(str(tmp_path))
    try:
        writer.set_attributes(
            sample_rate_hz=30000.0,
            electrode_rows=rows,
            broadband_lsb_uv=0.195,
        )
    finally:
        writer.file.close()
    return writer.filename


def test_writes_physical_electrode_ids(tmp_path):
    frame = BroadbandFrame(
        frame_data=[0, 0, 0, 0, 0],
        channel_ranges=[
            ChannelRange(
                type=ChannelType.ELECTRODE, count=5, channel_ids=[0, 1, 2, 3, 4]
            )
        ],
    )
    filename = write_attributes(
        tmp_path, frame, {0: 6, 1: 16, 2: 10, 3: 14, 4: 20}
    )

    with h5py.File(filename, "r") as f:
        electrodes = f["general/extracellular_ephys/electrodes"]
        assert electrodes["id"][:].tolist() == [6, 16, 10, 14, 20]
        assert electrodes["channel_id"][:].tolist() == [0, 1, 2, 3, 4]
        assert electrodes["channel_type"][:].tolist() == [0, 0, 0, 0, 0]
        assert electrodes.attrs["id_source"] == "electrode_map"
        assert electrodes.attrs["gpio_channel_id_offset"] == GPIO_CHANNEL_ID_OFFSET
        assert f.attrs["sample_rate_hz"] == 30000.0
        assert f.attrs["lsb_uv"] == 0.195


def test_electrode_table_length_matches_the_per_frame_entry_count(tmp_path):
    """GPIO rows are part of ElectricalSeries, so they need table rows too."""
    frame = BroadbandFrame(
        frame_data=[0, 0, 0],
        channel_ranges=[
            ChannelRange(type=ChannelType.ELECTRODE, count=2, channel_ids=[0, 1]),
            ChannelRange(type=ChannelType.GPIO, count=1, channel_ids=[1]),
        ],
    )
    filename = write_attributes(tmp_path, frame, {0: 6, 1: 16})

    with h5py.File(filename, "r") as f:
        electrodes = f["general/extracellular_ephys/electrodes"]
        assert len(electrodes["id"]) == len(frame.frame_data)
        assert electrodes["id"][:].tolist() == [6, 16, GPIO_CHANNEL_ID_OFFSET + 1]
        assert electrodes["channel_type"][:].tolist() == [0, 0, 1]


def test_records_the_legacy_fallback_in_id_source(tmp_path):
    frame = BroadbandFrame(frame_data=[0, 0, 0])
    filename = write_attributes(tmp_path, frame)

    with h5py.File(filename, "r") as f:
        electrodes = f["general/extracellular_ephys/electrodes"]
        assert electrodes["id"][:].tolist() == [0, 1, 2]
        assert electrodes.attrs["id_source"] == "positional"
