import pytest

from edge.serial_reader import parse_frame_line


def test_parse_valid_frame():
    parsed = parse_frame_line("FRAME:Rp:9663.52;I:1.034;status:FAIR;asym:0.1")
    assert parsed["rp_ohm"] == pytest.approx(9663.52)
    assert parsed["current_ua"] == pytest.approx(1.034)
    assert parsed["status"] == "FAIR"
    assert parsed["asym_percent"] == pytest.approx(0.1)


def test_parse_valid_without_asym():
    parsed = parse_frame_line("FRAME:Rp:10000;I:0.9;status:EXCELLENT")
    assert parsed["rp_ohm"] == pytest.approx(10000)
    assert parsed["current_ua"] == pytest.approx(0.9)
    assert parsed["status"] == "EXCELLENT"
    assert parsed["asym_percent"] is None


def test_parse_edge_numeric_formats():
    parsed = parse_frame_line("FRAME:Rp:1.0e4;I:-1.25e-1;status:warning;asym:0")
    assert parsed["rp_ohm"] == pytest.approx(10000.0)
    assert parsed["current_ua"] == pytest.approx(-0.125)
    assert parsed["status"] == "WARNING"
    assert parsed["asym_percent"] == pytest.approx(0.0)


def test_parse_rejects_missing_prefix():
    with pytest.raises(ValueError, match="missing_prefix"):
        parse_frame_line("Rp:9663.52;I:1.034;status:FAIR;asym:0.1")


def test_parse_rejects_missing_required_field():
    with pytest.raises(ValueError, match="missing_field:status"):
        parse_frame_line("FRAME:Rp:9663.52;I:1.034;asym:0.1")


def test_parse_rejects_invalid_numeric():
    with pytest.raises(ValueError, match="invalid_numeric"):
        parse_frame_line("FRAME:Rp:nope;I:1.034;status:FAIR;asym:0.1")