from workflows.nlu.response_normalizer import normalize_response


def test_normalize_yes_variants():
    canonical, confidence = normalize_response("yep, that works")
    assert canonical == "yes"
    assert confidence >= 0.85


def test_normalize_positive_phrase():
    canonical, confidence = normalize_response("sounds great to us")
    assert canonical == "positive"
    assert confidence >= 0.85


def test_normalize_proceed():
    canonical, confidence = normalize_response("let's do it")
    assert canonical == "proceed"
    assert confidence >= 0.85


def test_normalize_negative():
    canonical, confidence = normalize_response("nope")
    assert canonical == "no"
    assert confidence >= 0.85


def test_normalize_uncertain():
    canonical, confidence = normalize_response("I'm not sure about this")
    assert canonical == "uncertain"
    assert confidence >= 0.85


def test_normalize_none_when_no_match():
    canonical, confidence = normalize_response("maybe later")
    assert canonical is None
    assert confidence == 0.0
