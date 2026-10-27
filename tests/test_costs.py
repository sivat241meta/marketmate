import pytest

from app.costs import CostCapExceeded, CostLedger, spark_cost


def test_cap_blocks(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 0.01)
    ledger.add("meta", "muse-spark-1.3", 0.02)
    with pytest.raises(CostCapExceeded):
        ledger.check()


def test_cap_allows_under_cap(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 3.0)
    ledger.check()
    ledger.add("meta", "muse-spark-1.3", 0.02)
    assert ledger.today_usd() == pytest.approx(0.02)
    assert ledger.today_usd("baseten") == 0.0


def test_spark_cost():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert spark_cost(usage) == pytest.approx(5.50)
