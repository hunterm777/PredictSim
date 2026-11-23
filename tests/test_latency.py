import numpy as np
import pytest

from predictsim.latency import Fixed, LatencyConfig, LogNormal, Uniform


def test_models_are_seeded_and_integer() -> None:
    a, b = np.random.default_rng(3), np.random.default_rng(3)
    u, ln = Uniform(10, 20), LogNormal(1_000, 0.5)
    xs = [u.sample(a) for _ in range(50)] + [ln.sample(a) for _ in range(50)]
    ys = [u.sample(b) for _ in range(50)] + [ln.sample(b) for _ in range(50)]
    assert xs == ys and all(isinstance(x, int) and x >= 0 for x in xs)
    assert all(10 <= x <= 20 for x in xs[:50])
    assert Fixed(7).sample(a) == 7 and LatencyConfig().data == Fixed(0)


@pytest.mark.parametrize("build", [lambda: Fixed(-1), lambda: Uniform(5, 1), lambda: LogNormal(0, 1)])
def test_bad_parameters(build) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        build()
