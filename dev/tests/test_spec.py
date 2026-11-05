import pytest

from lumen_ops.spec import TOP_LEVEL_SECTIONS, load_spec

from lumen_dev.paths import SPEC


def test_spec_has_every_section_and_resolves_relative_times():
    spec = load_spec(SPEC)
    assert set(TOP_LEVEL_SECTIONS) <= set(spec.data)
    assert spec.at("-5h20m") == "2026-03-14T03:40:00Z"
    assert spec.at("-7h") == "2026-03-14T02:00:00Z"
    assert spec.at("2026-03-14T10:00:00Z") == "2026-03-14T10:00:00Z"


@pytest.mark.parametrize("bad", ["-", "-5x", "5h", "-h"])
def test_bad_relative_times_are_rejected(bad):
    with pytest.raises(ValueError):
        load_spec(SPEC).at(bad)
