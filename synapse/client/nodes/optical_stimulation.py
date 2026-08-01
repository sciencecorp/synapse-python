from typing import Optional, List
from synapse.api.node_pb2 import NodeConfig, NodeType
from synapse.api.nodes.optical_stimulation_pb2 import (
    OpticalStimulationConfig,
    DisplayMap,
)
from synapse.client.node import Node

# Maximum logical display dimension and physical pin value supported by the
# LUX16K / MUX01 gateware (must match MUX01_MAX_DIM / the 8-bit pin width).
MAX_DISPLAY_DIM = 128
MAX_PHYSICAL_PIN = 0xFF


# Ready-made physical pin maps for the displays that were previously hardcoded
# in the MUX01 gateware. Pass these as row_map/col_map to OpticalStimulation.

# BIDIR_BIOHYBRID_V1 (NeRV512U biohybrid), 12 rows x 23 cols.
BIOHYBRID_NERV512U_V1_ROW_MAP = [0, 64, 8, 72, 16, 80, 24, 88, 32, 96, 40, 104]
BIOHYBRID_NERV512U_V1_COL_MAP = [
    0, 1, 8, 9, 16, 17, 24, 25, 32, 33, 40, 41,
    48, 49, 56, 57, 64, 65, 72, 73, 74, 75, 76,
]

# LED breakout board (60110001), 32 rows x 64 cols.
# Rows interleave 0..15 with 64..79; cols are 0..31 then 64..95.
LED_BOARD_60110001_ROW_MAP = [
    v for i in range(16) for v in (i, i + 64)
]
LED_BOARD_60110001_COL_MAP = list(range(32)) + list(range(64, 96))


class OpticalStimulation(Node):
    type = NodeType.kOpticalStimulation

    def __init__(
        self,
        peripheral_id: int,
        pixel_mask: List[int],
        bit_width: int,
        frame_rate: int,
        gain: float,
        send_receipts: bool = False,
        row_map: Optional[List[int]] = None,
        col_map: Optional[List[int]] = None,
    ):
        self.pixel_mask = pixel_mask
        self.peripheral_id = peripheral_id
        self.bit_width = bit_width
        self.frame_rate = frame_rate
        self.gain = gain
        self.send_receipts = send_receipts
        # Optional physical pin mapping. row_map[logical_row] / col_map[logical_col]
        # give the physical chip pin; the lengths define the display dimensions.
        # Both must be supplied together (or neither).
        self.row_map = row_map
        self.col_map = col_map
        self._validate_display_map()

    def _validate_display_map(self):
        has_row = bool(self.row_map)
        has_col = bool(self.col_map)
        if has_row != has_col:
            raise ValueError(
                "row_map and col_map must both be provided together (or neither)"
            )
        if not has_row:
            return
        if len(self.row_map) > MAX_DISPLAY_DIM or len(self.col_map) > MAX_DISPLAY_DIM:
            raise ValueError(
                f"display map dimensions {len(self.row_map)}x{len(self.col_map)} "
                f"exceed maximum {MAX_DISPLAY_DIM}x{MAX_DISPLAY_DIM}"
            )
        for pin in list(self.row_map) + list(self.col_map):
            if pin < 0 or pin > MAX_PHYSICAL_PIN:
                raise ValueError(
                    f"display map pin {pin} out of range [0, {MAX_PHYSICAL_PIN}]"
                )
        if self.pixel_mask and len(self.pixel_mask) != len(self.row_map) * len(
            self.col_map
        ):
            raise ValueError(
                "pixel_mask length must equal len(row_map) * len(col_map) "
                "when a display map is provided"
            )

    def _to_proto(self):
        n = NodeConfig()
        p = OpticalStimulationConfig()
        p.peripheral_id = self.peripheral_id
        p.pixel_mask.extend(self.pixel_mask)
        p.bit_width = self.bit_width
        p.frame_rate = self.frame_rate
        p.gain = self.gain
        p.send_receipts = self.send_receipts
        if self.row_map and self.col_map:
            display_map = DisplayMap()
            display_map.row_map.extend(self.row_map)
            display_map.col_map.extend(self.col_map)
            p.display_map.CopyFrom(display_map)
        n.optical_stimulation.CopyFrom(p)
        return n

    @staticmethod
    def _from_proto(proto: Optional[OpticalStimulationConfig]):
        if proto is None:
            return OpticalStimulation(0, [], 0, 0, 0.0, False)

        if not isinstance(proto, OpticalStimulationConfig):
            raise ValueError("proto is not of type OpticalStimulationConfig")

        row_map = None
        col_map = None
        if proto.HasField("display_map"):
            row_map = list(proto.display_map.row_map)
            col_map = list(proto.display_map.col_map)

        return OpticalStimulation(
            peripheral_id=proto.peripheral_id,
            pixel_mask=list(proto.pixel_mask),
            bit_width=proto.bit_width,
            frame_rate=proto.frame_rate,
            gain=proto.gain,
            send_receipts=proto.send_receipts,
            row_map=row_map,
            col_map=col_map,
        )
