from clamp import clamp


def test_clamp_returns_lower_bound() -> None:
    assert clamp(-1, 0, 10) == 0


def test_clamp_returns_upper_bound() -> None:
    assert clamp(11, 0, 10) == 10


def test_clamp_keeps_value_in_range() -> None:
    assert clamp(5, 0, 10) == 5
