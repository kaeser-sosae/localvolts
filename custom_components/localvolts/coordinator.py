"""Coordinator for Localvolts integration."""

import asyncio
import datetime
import logging
from dateutil import parser, tz
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

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


        super().__init__(
            hass,
            _LOGGER,
            name="Localvolts Data",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the API endpoint."""
        current_utc_time: datetime.datetime = dt_util.utcnow()
        from_time: datetime.datetime = current_utc_time
        to_time: datetime.datetime = current_utc_time + datetime.timedelta(minutes=5)

        _LOGGER.debug("intervalEnd = %s", self.intervalEnd)
        _LOGGER.debug("lastUpdate = %s", self.lastUpdate)
        _LOGGER.debug("from_time = %s", from_time)
        _LOGGER.debug("to_time = %s", to_time)

        # Determine if we need to fetch new data
        if (self.intervalEnd is None) or (current_utc_time > self.intervalEnd):
            _LOGGER.debug("New interval detected. Retrieving the latest data.")
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
                self.time_past_start = datetime.timedelta(0)
                _LOGGER.warning("No 'exp' quality data returned for the interval; marking update as failed.")
                raise UpdateFailed("No 'exp' quality interval returned")
        else:
            _LOGGER.debug("Data did not change. Still in the same interval.")
            if self.intervalEnd:
                interval_start = self.intervalEnd - datetime.timedelta(minutes=5)
                elapsed = dt_util.utcnow() - interval_start
                # Clamp to zero to avoid negative durations when interval is in the future.
                self.time_past_start = elapsed if elapsed > datetime.timedelta(0) else datetime.timedelta(0)

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

        data: Any = None
        attempts = 3
        for attempt in range(1, attempts + 1):
            async with session.get(url, headers=headers) as response:
                if response.status == 401:
                    _LOGGER.critical("Unauthorized access: Check your API key.")
                    raise UpdateFailed("Unauthorized access: Invalid API key.")
                if response.status == 403:
                    _LOGGER.critical("Forbidden: Check your Partner ID.")
                    raise UpdateFailed("Forbidden: Invalid Partner ID.")
                if response.status == 429 or response.status >= 500:
                    if attempt == attempts:
                        raise UpdateFailed(f"Localvolts API returned {response.status}")
                    delay = 2 ** (attempt - 1)
                    _LOGGER.warning(
                        "Localvolts API returned %s. Retrying in %ss (attempt %s/%s).",
                        response.status,
                        delay,
                        attempt,
                        attempts,
                    )
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()
                data: Any = await response.json()
                break

        if isinstance(data, list) and not data:
            _LOGGER.warning(
                "No data received, check that your NMI, PartnerID and API Key are correct."
            )
            raise UpdateFailed("No data received: Invalid NMI?")

        if not isinstance(data, list):
            raise UpdateFailed("Unexpected API response format: expected list of intervals")

        return data

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
