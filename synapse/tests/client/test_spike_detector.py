from synapse.api.nodes.spike_detector_pb2 import SpikeDetectorConfig, TemplateMatcher, Thresholder
from synapse.client.nodes.spike_detector import SpikeDetector, ThresholderConfig, TemplateMatcherConfig

def test_thresholder_config():
    config = ThresholderConfig(threshold_uV=100)
    detector = SpikeDetector(samples_per_spike=100, config=config)
    
    assert detector.threshold_uV == 100
    assert detector.template_uV == []

def test_template_matcher_config():
    config = TemplateMatcherConfig(template_uV=[1, 2, 3])
    detector = SpikeDetector(samples_per_spike=100, config=config)
    
    assert detector.threshold_uV is None
    assert detector.template_uV == [1, 2, 3]

def test_invalid_config():
    try:
        SpikeDetector(samples_per_spike=100, config=None)
    except ValueError as e:
        assert str(e) == "invalid configuration type provided - must be ThresholderConfig or TemplateMatcherConfig"

def test_invalid_config_type():
    try:
        SpikeDetector(samples_per_spike=100, config="invalid")
    except ValueError as e:
        assert str(e) == "invalid configuration type provided - must be ThresholderConfig or TemplateMatcherConfig"

def test_from_proto_thresholder():
    proto = SpikeDetectorConfig(
        samples_per_spike=100,
        thresholder=Thresholder(threshold_uV=100)
    )
    detector = SpikeDetector._from_proto(proto)
    
    assert detector.samples_per_spike == 100
    assert detector.samples_per_spike == 100
    assert detector.threshold_uV == 100
    assert detector.template_uV == []

def test_from_proto_template_matcher():
    proto = SpikeDetectorConfig(
        samples_per_spike=100,
        template_matcher=TemplateMatcher(template_uV=[1, 2, 3])
    )
    detector = SpikeDetector._from_proto(proto)
    
    assert detector.samples_per_spike == 100
    assert detector.threshold_uV is None
    assert detector.template_uV == [1, 2, 3]

def test_to_proto_thresholder():
    config = ThresholderConfig(threshold_uV=100)
    detector = SpikeDetector(samples_per_spike=100, config=config)
    
    proto = detector._to_proto()
    
    assert proto.spike_detector.samples_per_spike == 100
    assert proto.spike_detector.HasField('thresholder')
    assert proto.spike_detector.thresholder.threshold_uV == 100
    assert not proto.spike_detector.HasField('template_matcher')

def test_to_proto_template_matcher():
    config = TemplateMatcherConfig(template_uV=[1, 2, 3])
    detector = SpikeDetector(samples_per_spike=100, config=config)
    
    proto = detector._to_proto()
    
    assert proto.spike_detector.samples_per_spike == 100
    assert proto.spike_detector.HasField('template_matcher')
    assert proto.spike_detector.template_matcher.template_uV == [1, 2, 3]
    assert not proto.spike_detector.HasField('thresholder')

if __name__ == '__main__':
    test_thresholder_config()
    test_template_matcher_config()
    test_invalid_config()
    test_invalid_config_type()
    test_from_proto_thresholder()
    test_from_proto_template_matcher()
    test_to_proto_thresholder()
    test_to_proto_template_matcher()
    print("All tests passed!")

