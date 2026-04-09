import pytest
from synapse.api.nodes.image_sink_pb2 import ImageSinkConfig
from synapse.client.nodes.image_sink import ImageSink


def test_image_sink_to_proto():
    sink = ImageSink(
        peripheral_id=1,
        frame_rate_hz=30,
    )

    proto = sink._to_proto()

    assert proto.image_sink.peripheral_id == 1
    assert proto.image_sink.frame_rate_hz == 30


def test_image_sink_from_proto():
    proto = ImageSinkConfig(
        peripheral_id=2,
        frame_rate_hz=60,
    )

    sink = ImageSink._from_proto(proto)

    assert sink.peripheral_id == 2
    assert sink.frame_rate_hz == 60


def test_image_sink_from_proto_roundtrip():
    original = ImageSink(
        peripheral_id=5,
        frame_rate_hz=24,
    )

    proto = original._to_proto()
    restored = ImageSink._from_proto(proto.image_sink)

    assert restored.peripheral_id == original.peripheral_id
    assert restored.frame_rate_hz == original.frame_rate_hz


def test_image_sink_from_invalid_proto():
    with pytest.raises(ValueError, match="missing"):
        ImageSink._from_proto(None)

    with pytest.raises(ValueError, match="not of type"):
        ImageSink._from_proto("invalid")
