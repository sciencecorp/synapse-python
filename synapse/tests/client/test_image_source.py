import pytest
from synapse.api.datatype_pb2 import PixelFormat
from synapse.api.nodes.image_source_pb2 import ImageSourceConfig
from synapse.client.nodes.image_source import ImageSource


def test_image_source_to_proto():
    source = ImageSource(
        peripheral_id=1,
        width=1920,
        height=1080,
        format=PixelFormat.kRGB888,
        frame_rate_hz=30,
    )

    proto = source._to_proto()

    assert proto.image_source.peripheral_id == 1
    assert proto.image_source.width == 1920
    assert proto.image_source.height == 1080
    assert proto.image_source.format == PixelFormat.kRGB888
    assert proto.image_source.frame_rate_hz == 30


def test_image_source_to_proto_pixel_formats():
    for fmt in [
        PixelFormat.kPixelFormatUnknown,
        PixelFormat.kYUV420_888,
        PixelFormat.kRGB888,
        PixelFormat.kRGBA8888,
        PixelFormat.kGrayscale8,
        PixelFormat.kRAW10,
        PixelFormat.kRAW16,
        PixelFormat.kNV12,
        PixelFormat.kNV21,
    ]:
        source = ImageSource(
            peripheral_id=0,
            width=640,
            height=480,
            format=fmt,
            frame_rate_hz=60,
        )
        proto = source._to_proto()
        assert proto.image_source.format == fmt


def test_image_source_from_proto():
    proto = ImageSourceConfig(
        peripheral_id=2,
        width=3840,
        height=2160,
        format=PixelFormat.kNV21,
        frame_rate_hz=15,
    )

    source = ImageSource._from_proto(proto)

    assert source.peripheral_id == 2
    assert source.width == 3840
    assert source.height == 2160
    assert source.format == PixelFormat.kNV21
    assert source.frame_rate_hz == 15


def test_image_source_from_proto_roundtrip():
    original = ImageSource(
        peripheral_id=3,
        width=1280,
        height=720,
        format=PixelFormat.kGrayscale8,
        frame_rate_hz=120,
    )

    proto = original._to_proto()
    restored = ImageSource._from_proto(proto.image_source)

    assert restored.peripheral_id == original.peripheral_id
    assert restored.width == original.width
    assert restored.height == original.height
    assert restored.format == original.format
    assert restored.frame_rate_hz == original.frame_rate_hz


def test_image_source_from_invalid_proto():
    with pytest.raises(ValueError, match="missing"):
        ImageSource._from_proto(None)

    with pytest.raises(ValueError, match="not of type"):
        ImageSource._from_proto("invalid")
