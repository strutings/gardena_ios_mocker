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

    devices = coordinator.data.get("devices", []) if coordinator.data else []
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
        """Initialize core unique entity references and supported capabilities attributes."""
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._entry = entry
        
        self._attr_unique_id = f"{self._device_id}_mower"
        self._attr_name = None  # None ensures it inherits the main device name grouping automatically
        self._attr_supported_features = (
            LawnMowerEntityFeature.START_MOWING
            | LawnMowerEntityFeature.PAUSE
            | LawnMowerEntityFeature.DOCK
        )

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the mower's current activity based on both status properties and schedule overrides."""
        devices = self.coordinator.data.get("devices", []) if self.coordinator.data else []
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

    async def async_start_mowing(self, **kwargs: Any) -> None:
        """Home Assistant command to start mowing / resume schedule."""
        _LOGGER.info("Home Assistant standard command intercepted: Resuming regular mower schedule sequence")
        # Direct integration mapping to clear the cloud-side schedule suspension block
        await self.coordinator.api_manager.async_send_mower_setting("schedules_paused_until", "")
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def async_pause(self, **kwargs: Any) -> None:
        """Home Assistant command to pause the mower."""
        _LOGGER.info("Home Assistant standard command intercepted: Pausing mower scheduling infinitely")
        # Direct integration mapping to leverage the 2040 epoch infinite hold setting path
        await self.coordinator.api_manager.async_send_mower_setting("schedules_paused_until", "2040-12-31T22:00:00.000Z")
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def async_dock(self, **kwargs: Any) -> None:
        """Home Assistant command to dock the mower."""
        _LOGGER.info("Home Assistant standard command intercepted: Ordering mower back to charging station grid")
        # Direct integration mapping to execute the precise app-level command destination
        await self.coordinator.api_manager.async_send_mower_action("park_until_next_schedule", {})
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }
