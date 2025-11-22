"""Coordinator for Localvolts integration."""

import datetime
import logging
from dateutil import parser, tz
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import aiohttp

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = datetime.timedelta(seconds=10)  # Update every 10 seconds

class LocalvoltsDataUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator to manage fetching data from Localvolts API."""

    #def __init__(self, hass: HomeAssistant, api_key, partner_id, nmi_id):
    def __init__(
        self,
        hass: HomeAssistant,
        api_key: str,
        partner_id: str,
        nmi_id: str,
    ) -> None:
        """Initialize the coordinator."""
        #self.api_key = api_key
        #self.partner_id = partner_id
        #self.nmi_id = nmi_id
        #self.intervalEnd = None
        #self.lastUpdate = None
        #self.time_past_start = datetime.timedelta(0)
        #self.data = {}
        self.api_key: str = api_key
        self.partner_id: str = partner_id
        self.nmi_id: str = nmi_id
        self.intervalEnd: Any = None
        self.lastUpdate: Any = None
        self.time_past_start: datetime.timedelta = datetime.timedelta(0)
        self.data: Dict[str, Any] = {}
        self.today_cost_cents: float | None = None
        self.month_cost_cents: float | None = None
        self.today_cost_error: Optional[str] = None
        self.month_cost_error: Optional[str] = None


        super().__init__(
            hass,
            _LOGGER,
            name="Localvolts Data",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the API endpoint."""
        current_utc_time: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
        from_time: datetime.datetime = current_utc_time
        to_time: datetime.datetime = current_utc_time + datetime.timedelta(minutes=5)

        _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
        _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
        _LOGGER.debug("from_time = %s", from_time)
        _LOGGER.debug("to_time = %s", to_time)

        # Determine if we need to fetch new data
        if (self.intervalEnd is None) or (current_utc_time > self.intervalEnd):
            _LOGGER.debug("New interval detected. Retrieving the latest data.")
            from_time_str: str = from_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_time_str: str = to_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            url: str = (
                f"https://api.localvolts.com/v1/customer/interval?"
                f"NMI={self.nmi_id}&from={from_time_str}&to={to_time_str}"
            )

            headers: Dict[str, str] = {
                "Authorization": f"apikey {self.api_key}",
                "partner": self.partner_id,
            }

            try:
                session = async_get_clientsession(self.hass)
                data = await self._fetch_intervals(session, from_time, to_time)
            
            
            except aiohttp.ClientError as e:
                _LOGGER.error("Failed to fetch data from Localvolts API: %s", str(e))
                raise UpdateFailed(f"Error communicating with API: {e}") from e

            # Process data
            new_data_found = False
            for item in data:
                if item.get("quality", "").lower() == "exp":
                    interval_end = parser.isoparse(item["intervalEnd"])
                    last_update_time = parser.isoparse(item["lastUpdate"])

                    # Ensure timezone awareness
                    if interval_end.tzinfo is None:
                        interval_end = interval_end.replace(tzinfo=tz.UTC)
                    if last_update_time.tzinfo is None:
                        last_update_time = last_update_time.replace(tzinfo=tz.UTC)

                    # Update variables
                    self.intervalEnd = interval_end
                    self.lastUpdate = last_update_time
                    self.data = item

                    interval_start: datetime.datetime = interval_end - datetime.timedelta(minutes=5)
                    self.time_past_start = last_update_time - interval_start
                    _LOGGER.debug(
                        "Data updated: intervalEnd=%s, lastUpdate=%s",
                        self.intervalEnd,
                        self.lastUpdate,
                    )
                    new_data_found = True
                    break
                else:
                    _LOGGER.debug(
                        "Skipping non-'exp' quality data. Only 'exp' is processed."
                    )
            if not new_data_found:
                _LOGGER.debug("No new data with 'exp' quality found. Retaining last known data.")
                # Do not update self.time_past_start; retain the last known value
                # Optionally, you can log the time since the last update if needed
            else:
                # Update aggregated costs (today and this month) after a new interval is found.
                try:
                    await self._update_aggregated_costs(session, current_utc_time)
                except Exception as err:  # noqa: BLE001
                    # Do not fail the coordinator if aggregation fails; only aggregation sensors should break.
                    _LOGGER.debug("Aggregation update failed (sensors will show unavailable): %s", err)
        else:
            _LOGGER.debug("Data did not change. Still in the same interval.")

        # Return self.data to comply with DataUpdateCoordinator requirements
        return self.data

    async def _fetch_intervals(
        self,
        session: aiohttp.ClientSession,
        from_time: datetime.datetime,
        to_time: datetime.datetime,
    ) -> List[Dict[str, Any]]:
        """Fetch interval data from the Localvolts API."""
        from_time_str: str = self._format_time(from_time)
        to_time_str: str = self._format_time(to_time)

        url: str = (
            f"https://api.localvolts.com/v1/customer/interval?"
            f"NMI={self.nmi_id}&from={from_time_str}&to={to_time_str}"
        )

        headers: Dict[str, str] = {
            "Authorization": f"apikey {self.api_key}",
            "partner": self.partner_id,
        }

        async with session.get(url, headers=headers) as response:
            if response.status == 401:
                _LOGGER.critical("Unauthorized access: Check your API key.")
                raise UpdateFailed("Unauthorized access: Invalid API key.")
            if response.status == 403:
                _LOGGER.critical("Forbidden: Check your Partner ID.")
                raise UpdateFailed("Forbidden: Invalid Partner ID.")

            response.raise_for_status()
            data: Any = await response.json()

        if isinstance(data, list) and not data:
            _LOGGER.warning(
                "No data received, check that your NMI, PartnerID and API Key are correct."
            )
            raise UpdateFailed("No data received: Invalid NMI?")

        if not isinstance(data, list):
            raise UpdateFailed("Unexpected API response format: expected list of intervals")

        return data

    async def _update_aggregated_costs(
        self, session: aiohttp.ClientSession, now_utc: datetime.datetime
    ) -> None:
        """Update totals for today and this month (costsAll in cents)."""
        # Ensure timezone-aware UTC
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)
        else:
            now_utc = now_utc.astimezone(datetime.timezone.utc)

        start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Reset errors and compute aggregates safely
        self.today_cost_error = None
        self.month_cost_error = None

        day_intervals = await self._safe_fetch_intervals(session, start_of_day, now_utc, "today")
        if day_intervals is not None:
            self.today_cost_cents = self._sum_costs(day_intervals)
        else:
            self.today_cost_cents = None
            self.today_cost_error = "Failed to fetch today's intervals"

        month_intervals = await self._safe_fetch_intervals(session, start_of_month, now_utc, "month")
        if month_intervals is not None:
            self.month_cost_cents = self._sum_costs(month_intervals)
        else:
            self.month_cost_cents = None
            self.month_cost_error = "Failed to fetch month intervals"

        _LOGGER.debug(
            "Aggregated costs updated: today=%s cents, month=%s cents",
            self.today_cost_cents,
            self.month_cost_cents,
        )

    async def _safe_fetch_intervals(
        self,
        session: aiohttp.ClientSession,
        from_time: datetime.datetime,
        to_time: datetime.datetime,
        label: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch intervals for aggregation without breaking the coordinator."""
        try:
            return await self._fetch_intervals(session, from_time, to_time)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Skipping %s aggregation due to error: %s", label, err)
            return None

    @staticmethod
    def _sum_costs(intervals: List[Dict[str, Any]]) -> float:
        """Sum costsAll for intervals marked with quality 'exp'."""
        total = 0.0
        for item in intervals:
            if item.get("quality", "").lower() != "exp":
                continue
            value = item.get("costsAll")
            if value is None:
                continue
            try:
                total += float(value)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _format_time(dt_obj: datetime.datetime) -> str:
        """Format datetime as Localvolts API expects (UTC, Z suffix)."""
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_obj = dt_obj.astimezone(datetime.timezone.utc)
        return dt_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
