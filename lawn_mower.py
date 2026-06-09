import logging
from typing import Any
import aiohttp
from homeassistant.components.lawn_mower import (
    LawnMowerEntity,
    LawnMowerEntityFeature,
    LawnMowerActivity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up Gardena mower control."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    devices = coordinator.data.get("devices", [])
    for device in devices:
        abilities = device.get("abilities", [])
        for ability in abilities:
            if ability.get("type") == "robotic_mower":
                entities.append(GardenaMower(coordinator, device, entry))

    async_add_entities(entities)

class GardenaMower(CoordinatorEntity, LawnMowerEntity):
    """Representation of a controllable Gardena mower."""

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._entry = entry
        
        self._attr_unique_id = f"{self._device_id}_mower"
        self._attr_name = self._device_name
        self._attr_supported_features = (
            LawnMowerEntityFeature.START_MOWING
            | LawnMowerEntityFeature.PAUSE
            | LawnMowerEntityFeature.DOCK
        )

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the mower's current activity based on API data."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == "robotic_mower":
                        for prop in ability.get("properties", []):
                            if prop.get("name") == "status":
                                val = prop.get("value")
                                
                                if isinstance(val, dict):
                                    status_str = val.get("main", "")
                                else:
                                    status_str = str(val) if val else ""

                                # FIXED: Normalize the string to lowercase and match against genuine app states
                                status_clean = status_str.strip().lower()

                                if status_clean in ["mowing", "ok_cutting", "ok_cutting_timer_override", "cutting"]:
                                    return LawnMowerActivity.MOWING
                                elif status_clean in ["parked", "parked_timer", "parked_park_selected", "ok_charging", "charging", "completed"]:
                                    return LawnMowerActivity.DOCKED
                                elif status_clean in ["paused", "paused_timer"]:
                                    return LawnMowerActivity.PAUSED
                                elif status_clean in ["error", "offline", "fatal_error", "needs_service"]:
                                    return LawnMowerActivity.ERROR
        return None

    async def _send_mower_command(self, command_id: str, parameters: dict = None) -> None:
        """Send a control command to the BFF API mimicking the iOS app configuration."""
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token

        location_id = self._entry.data["location_id"]
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/commands?locationId={location_id}"
        
        payload = {
            "id": command_id,
            "abilityId": "robotic_mower",
            "deviceId": self._device_id
        }
        if parameters:
            payload["parameters"] = parameters

        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,  # Double configuration fallback for the command gateway
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            "Accept": "application/json"
        }

        try:
            async with manager.session.post(url, json=payload, headers=headers, timeout=10) as response:
                if response.status == 401:
                    token = await manager.async_authenticate()
                    headers["Authorization"] = f"Bearer {token}"
                    async with manager.session.post(url, json=payload, headers=headers, timeout=10) as retry_resp:
                        if retry_resp.status not in [200, 202]:
                            _LOGGER.error("Error sending command after re-authentication: %s", retry_resp.status)
                elif response.status not in [200, 202]:
                    resp_txt = await response.text()
                    _LOGGER.error("Command %s failed with status %s: %s", command_id, response.status, resp_txt)
                else:
                    _LOGGER.info("Command %s successfully sent to %s", command_id, self._device_name)
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err:
            _LOGGER.error("Network error while sending command: %s", err)

    async def async_start_mowing(self, **kwargs: Any) -> None:
        """Home Assistant command to start mowing."""
        await self._send_mower_command("START", {"duration": 1440})

    async def async_pause(self, **kwargs: Any) -> None:
        """Home Assistant command to pause the mower."""
        await self._send_mower_command("PAUSE")

    async def async_dock(self, **kwargs: Any) -> None:
        """Home Assistant command to dock the mower."""
        await self._send_mower_command("PARK_UNTIL_NEXT_TASK")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }
