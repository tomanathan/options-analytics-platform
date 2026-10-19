from datetime import date
from typing import Any, cast

import pytest
from airflow.exceptions import AirflowFailException

from dags import daily_chain_snapshot


def test_snapshot_without_credentials_fails_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(daily_chain_snapshot, "_session", lambda: date(2026, 10, 16))
    task = daily_chain_snapshot.daily_chain_snapshot().get_task("snapshot")

    with pytest.raises(AirflowFailException, match="ALPACA_API_KEY"):
        cast(Any, task).python_callable()
