import pytest

from predictsim.fees import CustomFees, FeeInput

INP = FeeInput(1, 500_000, 10_000, False, True, 5_000_000)


def test_custom_function() -> None:
    fees = CustomFees(lambda f: 0 if f.is_maker else f.size)
    assert fees.charge(INP).total == 10_000
    assert fees.quote(INP) == 10_000
    assert fees.settle_fee(1_000_000, 100) == 0
    assert fees.fresh() is fees


def test_custom_function_must_return_int() -> None:
    with pytest.raises(TypeError):
        CustomFees(lambda f: 1.5).charge(INP)  # type: ignore[arg-type,return-value]
