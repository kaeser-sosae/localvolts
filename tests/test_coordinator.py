import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.localvolts.coordinator import (
    LocalvoltsDataUpdateCoordinator,
    UpdateFailed,
)


def test_format_time_converts_to_utc():
    naive = datetime.datetime(2023, 1, 1, 12, 0, 0)
    aware = datetime.datetime(
        2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=10))
    )

    assert LocalvoltsDataUpdateCoordinator._format_time(naive) == "2023-01-01T12:00:00Z"
    assert LocalvoltsDataUpdateCoordinator._format_time(aware) == "2023-01-01T02:00:00Z"


def test_sum_costs_only_counts_exp_quality():
    intervals = [
        {"quality": "exp", "costsAll": 5},
        {"quality": "raw", "costsAll": 10},
        {"quality": "EXP", "costsAll": "7"},
        {"quality": "exp", "costsAll": None},
        {"quality": "exp", "costsAll": "bad"},
    ]
    assert LocalvoltsDataUpdateCoordinator._sum_costs(intervals) == 12.0


@pytest.mark.asyncio
async def test_async_update_data_fetches_new_interval(monkeypatch):
    base_time = datetime.datetime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(
        "custom_components.localvolts.coordinator.dt_util.utcnow", lambda: base_time
    )

    coordinator = LocalvoltsDataUpdateCoordinator.__new__(
        LocalvoltsDataUpdateCoordinator
    )
    coordinator.hass = MagicMock()
    coordinator.api_key = "key"
    coordinator.partner_id = "partner"
    coordinator.nmi_id = "nmi"
    coordinator.intervalEnd = None
    coordinator.lastUpdate = None
    coordinator.time_past_start = datetime.timedelta(0)
    coordinator.data = {}

    monkeypatch.setattr(
        "custom_components.localvolts.coordinator.async_get_clientsession",
        lambda hass: MagicMock(name="session"),
    )

    interval_end = base_time + datetime.timedelta(minutes=5)
    last_update = interval_end

    mock_fetch = AsyncMock(
        return_value=[
            {
                "quality": "exp",
                "intervalEnd": interval_end.isoformat(),
                "lastUpdate": last_update.isoformat(),
                "costsAll": 10,
            }
        ]
    )
    monkeypatch.setattr(coordinator, "_fetch_intervals", mock_fetch)

    result = await coordinator._async_update_data()

    assert mock_fetch.await_count == 1
    assert coordinator.intervalEnd == interval_end
    assert coordinator.lastUpdate == last_update
    assert coordinator.time_past_start == datetime.timedelta(minutes=5)
    assert result["costsAll"] == 10


@pytest.mark.asyncio
async def test_async_update_data_skips_fetch_within_same_interval(monkeypatch):
    start_time = datetime.datetime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(
        "custom_components.localvolts.coordinator.dt_util.utcnow",
        lambda: start_time + datetime.timedelta(minutes=2),
    )

    coordinator = LocalvoltsDataUpdateCoordinator.__new__(
        LocalvoltsDataUpdateCoordinator
    )
    coordinator.hass = MagicMock()
    coordinator.api_key = "key"
    coordinator.partner_id = "partner"
    coordinator.nmi_id = "nmi"
    coordinator.intervalEnd = start_time + datetime.timedelta(minutes=5)
    coordinator.lastUpdate = start_time + datetime.timedelta(minutes=1)
    coordinator.time_past_start = datetime.timedelta(0)
    coordinator.data = {"costsAll": 3}

    mock_fetch = AsyncMock()
    monkeypatch.setattr(coordinator, "_fetch_intervals", mock_fetch)

    result = await coordinator._async_update_data()

    assert mock_fetch.await_count == 0
    assert coordinator.time_past_start == datetime.timedelta(minutes=2)
    assert result == {"costsAll": 3}


@pytest.mark.asyncio
async def test_async_update_data_marks_failure_without_exp(monkeypatch):
    base_time = datetime.datetime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(
        "custom_components.localvolts.coordinator.dt_util.utcnow", lambda: base_time
    )

    coordinator = LocalvoltsDataUpdateCoordinator.__new__(
        LocalvoltsDataUpdateCoordinator
    )
    coordinator.hass = MagicMock()
    coordinator.api_key = "key"
    coordinator.partner_id = "partner"
    coordinator.nmi_id = "nmi"
    coordinator.intervalEnd = None
    coordinator.lastUpdate = None
    coordinator.time_past_start = datetime.timedelta(seconds=30)
    coordinator.data = {}

    monkeypatch.setattr(
        "custom_components.localvolts.coordinator.async_get_clientsession",
        lambda hass: MagicMock(name="session"),
    )

    mock_fetch = AsyncMock(
        return_value=[
            {
                "quality": "raw",
                "intervalEnd": base_time.isoformat(),
                "lastUpdate": base_time.isoformat(),
            }
        ]
    )
    monkeypatch.setattr(coordinator, "_fetch_intervals", mock_fetch)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.time_past_start == datetime.timedelta(0)
