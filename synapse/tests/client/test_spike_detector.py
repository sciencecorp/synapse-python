from synapse.client.nodes.spike_detector import SpikeDetector, ThresholderConfig, TemplateMatcherConfig

def test_thresholder_config():
    config = ThresholderConfig(threshold_uV=100)
    detector = SpikeDetector(config=config)
    
    assert detector.threshold_uV == 100
    assert detector.template_uV == []

def test_template_matcher_config():
    config = TemplateMatcherConfig(template_uV=[1, 2, 3])
    detector = SpikeDetector(config=config)
    
    assert detector.threshold_uV is None
    assert detector.template_uV == [1, 2, 3]

def test_invalid_config():
    try:
        SpikeDetector(config=None)
    except ValueError as e:
        assert str(e) == "invalid configuration type provided - must be ThresholderConfig or TemplateMatcherConfig"

def test_invalid_config_type():
    try:
        SpikeDetector(config="invalid")
    except ValueError as e:
        assert str(e) == "invalid configuration type provided - must be ThresholderConfig or TemplateMatcherConfig"

