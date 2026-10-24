from znacht.domain.household import HealthMarker
from znacht.domain.recipe import Tag
from znacht.services.health import rules_from_markers


def test_only_flagged_markers_produce_rules():
    markers = [
        HealthMarker(name="Triglycerides", value=2.4, unit="mmol/l", flag="high"),
        HealthMarker(name="LDL cholesterol", value=2.9, unit="mmol/l"),  # not flagged
        HealthMarker(name="Ferritin", value=12, unit="ug/l", flag="low"),
    ]
    rules = rules_from_markers(markers)
    texts = [r.text for r in rules]
    assert any("added sugar" in t for t in texts)
    assert any("iron" in t for t in texts)
    assert not any("saturated" in t for t in texts)
    assert Tag.FISH in rules[0].tags


def test_duplicate_rules_are_merged():
    markers = [
        HealthMarker(name="hba1c", value=6.1, flag="high"),
        HealthMarker(name="glucose", value=6.5, flag="high"),
    ]
    assert len(rules_from_markers(markers)) == 2  # distinct texts
    markers = [
        HealthMarker(name="haemoglobin", value=11, flag="low"),
        HealthMarker(name="hemoglobin", value=11, flag="low"),
    ]
    assert len(rules_from_markers(markers)) == 1
