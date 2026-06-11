import logging
from typing import Any
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

    has_entity_name = True

    def __init__(self, coordinator, device, entry):
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._entry = entry
        
        self._attr_unique_id = f"{self._device_id}_mower"
        self._attr_name = None  # None gjør at den arver hovednavnet til enheten automatisk
        self._attr_supported_features = (
            LawnMowerEntityFeature.START_MOWING
            | LawnMowerEntityFeature.PAUSE
            | LawnMowerEntityFeature.DOCK
        )

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the mower's current activity based on both status properties and schedule overrides."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                
                # 1. First check if the live ability status reports a specific active state
                for ability in d.get("abilities", []):
                    if ability.get("type") == "robotic_mower":
                        for prop in ability.get("properties", []):
                            if prop.get("name") == "status":
                                val = prop.get("value")
                                
                                if isinstance(val, dict):
                                    status_str = val.get("main", "")
                                else:
                                    status_str = str(val) if val else ""

                                status_clean = status_str.strip().lower()

                                # Explicitly catch 'ok_cutting' and map it to mowing activity
                                if status_clean in ["mowing", "ok_cutting", "ok_cutting_timer_override", "cutting"]:
                                    return LawnMowerActivity.MOWING
                                elif status_clean in ["parked", "parked_timer", "parked_park_selected", "ok_charging", "charging", "completed"]:
                                    return LawnMowerActivity.DOCKED
                                elif status_clean in ["paused", "paused_timer"]:
                                    return LawnMowerActivity.PAUSED
                                elif status_clean in ["error", "offline", "fatal_error", "needs_service"]:
                                    return LawnMowerActivity.ERROR

                # 2. If status is ambiguous, check if the schedule is actively paused via settings override
                for setting in d.get("settings", []):
                    if setting.get("name") == "schedules_paused_until":
                        pause_val = setting.get("value")
                        if pause_val and len(str(pause_val).strip()) > 0:
                            return LawnMowerActivity.PAUSED

        # Default fallback to docked state if no explicit states are discovered
        return LawnMowerActivity.DOCKED

    async def _send_mower_command(self, target_value: str) -> None:
        """Send a schedule update to the BFF API mimicking the verified iOS app settings call."""
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token

        location_id = self._entry.data["location_id"]
        
        setting_id = None
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if setting.get("name") == "schedules_paused_until":
                        setting_id = setting.get("id")
                        break
        
        if not setting_id:
            setting_id = "9fd7a43c-539f-42be-a4ad-2dd79520722b"

        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/settings/{setting_id}?locationId={location_id}"
        
        payload = {
            "settings": {
                "name": "schedules_paused_until",
                "value": target_value,
                "device": self._device_id
            }
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Cargo 5.0.1"
        }

        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]:
                    # RETTET: Endret fra target_state til target_value for å unngå NameError krasj
                    _LOGGER.info("Successfully updated mower schedule state to: %s", target_value if target_value else "RESUME/START")
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
                else:
                    resp_txt = await response.text()
                    _LOGGER.error("Mower schedule configuration update failed with status %s: %s", response.status, resp_txt)
        except Exception as err:
            _LOGGER.error("Network error while sending schedule update command: %s", err)

    async def async_start_mowing(self, **kwargs: Any) -> None:
        """Home Assistant command to start mowing / resume schedule."""
        await self._send_mower_command("")

    async def async_pause(self, **kwargs: Any) -> None:
        """Home Assistant command to pause the mower."""
        await self._send_mower_command("2040-12-31T22:00:00Z")

    async def async_dock(self, **kwargs: Any) -> None:
        """Home Assistant command to dock the mower."""
        await self._send_mower_command("2040-12-31T22:00:00Z")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }
