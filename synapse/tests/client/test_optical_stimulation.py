import pytest

from synapse.api.nodes.optical_stimulation_pb2 import OpticalStimulationConfig
from synapse.client.nodes.optical_stimulation import (
    BIOHYBRID_NERV512U_23X23_COL_MAP,
    BIOHYBRID_NERV512U_23X23_ROW_MAP,
    OpticalStimulation,
)

ROWS = BIOHYBRID_NERV512U_23X23_ROW_MAP
COLS = BIOHYBRID_NERV512U_23X23_COL_MAP


def make(**kw):
    args = dict(peripheral_id=101, pixel_mask=[], bit_width=8, frame_rate=30, gain=1.0)
    args.update(kw)
    return OpticalStimulation(**args)


def test_display_map_round_trips():
    proto = make(row_map=ROWS, col_map=COLS)._to_proto()
    assert list(proto.optical_stimulation.display_map.row_map) == ROWS
    assert list(proto.optical_stimulation.display_map.col_map) == COLS

    node = OpticalStimulation._from_proto(proto.optical_stimulation)
    assert node.row_map == ROWS
    assert node.col_map == COLS


def test_no_display_map_leaves_field_unset():
    proto = make()._to_proto()
    assert not proto.optical_stimulation.HasField("display_map")
    node = OpticalStimulation._from_proto(OpticalStimulationConfig())
    assert node.row_map is None and node.col_map is None


@pytest.mark.parametrize(
    "kw",
    [
        dict(row_map=ROWS),
        dict(col_map=COLS),
        dict(row_map=[0] * 129, col_map=COLS),
        dict(row_map=[256], col_map=COLS),
        dict(row_map=ROWS, col_map=COLS, pixel_mask=[1] * 10),
    ],
)
def test_invalid_display_map_rejected(kw):
    with pytest.raises(ValueError):
        make(**kw)
