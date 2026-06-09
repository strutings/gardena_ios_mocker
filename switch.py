import logging
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up switches for mower configuration and irrigation devices."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    devices = coordinator.data.get("devices", [])
    for device in devices:
        device_id = device.get("id")
        device_name = device.get("name")
        abilities = device.get("abilities", [])
        
        # 1. GENERATE MOWER SWITCHES
        for ability in abilities:
            if ability.get("type") == "robotic_mower":
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "eco_mode", "Eco Mode", "mdi:leaf", entry))
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "mower_house", "Garage Protection", "mdi:garage-open", entry))
                break

        # 2. GENERATE IRRIGATION SWITCHES
        for ability in abilities:
            if ability.get("type") == "watering":
                _LOGGER.info("Registering irrigation switch for: %s", device_name)
                entities.append(GardenaWateringSwitch(coordinator, device, ability, entry))

    async_add_entities(entities)


class GardenaMowerConfigSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle configuration flags on the mower."""
    def __init__(self, coordinator, device_id, device_name, config_key, name_suffix, icon, entry):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._config_key = config_key
        self._entry = entry
        self._attr_unique_id = f"{device_id}_mower_switch_{config_key}_real_api"
        self._attr_name = f"{device_name} {name_suffix}"
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                configuration = d.get("configuration", {})
                if self._config_key in configuration: return bool(configuration[self._config_key])
                for setting in d.get("settings", []):
                    if setting.get("name") == self._config_key: return bool(setting.get("value", False))
        return False

    async def _update_mower_config(self, target_state: bool) -> None:
        manager = self.coordinator.api_manager
        token = manager._token
        location_id = self._entry.data["location_id"]
        setting_id = None
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if setting.get("name") == self._config_key: setting_id = setting.get("id"); break
        if not setting_id: return
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/settings/{setting_id}?locationId={location_id}"
        payload = {"settings": {"name": self._config_key, "value": target_state, "device": self._device_id}}
        headers = {"Authorization": f"Bearer {token}", "Authorization-Provider": "husqvarna", "X-Api-Key": CLIENT_ID, "Content-Type": "application/json"}
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]: self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err: _LOGGER.error("Error modifying mower switch configuration: %s", err)

    async def async_turn_on(self, **kwargs: Any) -> None: await self._update_mower_config(True)
    async def async_turn_off(self, **kwargs: Any) -> None: await self._update_mower_config(False)

    @property
    def device_info(self): return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaWateringSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to start and stop irrigation manually using the properties API extracted from the HAR analysis."""

    def __init__(self, coordinator, device, ability, entry):
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._ability_id = "watering"
        self._entry = entry
        self._attr_unique_id = f"{self._device_id}_watering_switch"
        self._attr_name = f"{self._device_name} Irrigation"
        self._attr_icon = "mdi:water-pump"

    @property
    def is_on(self) -> bool:
        """Check if the valve is currently irrigating."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == "watering":
                        for prop in ability.get("properties", []):
                            if prop.get("name") == "watering_timer_1":
                                val = prop.get("value", {})
                                if isinstance(val, dict):
                                    return str(val.get("state", "")).lower() in ["watering", "manual", "valve_open", "active"]
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Converts slider minutes to seconds and transmits 'manual' state via PUT."""
        duration_min = self.hass.data[DOMAIN].get(f"{self._device_id}_irrigation_time", 30)
        duration_sec = int(duration_min * 60)
        
        _LOGGER.info("Starting irrigation on %s for %s seconds (manual)...", self._device_name, duration_sec)
        await self._send_watering_property_update("manual", duration_sec)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stops irrigation by resetting the property state to 'idle' and duration to 0."""
        _LOGGER.info("Stopping irrigation on %s (idle)...", self._device_name)
        await self._send_watering_property_update("idle", 0)

    async def _send_watering_property_update(self, target_state: str, duration_sec: int) -> None:
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        
        # Target endpoint: Directly modifies the object's property tree hierarchy
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/abilities/watering/properties/watering_timer_1?locationId={location_id}"
        
        # Payload architecture: Encapsulated inside 'properties' -> 'value'
        payload = {
            "properties": {
                "name": "watering_timer_1",
                "value": {
                    "state": target_state,
                    "duration": duration_sec,
                    "valve_id": 1
                }
            }
        }
            
        headers = {
            "Authorization": f"Bearer {token}", 
            "Authorization-Provider": "husqvarna", 
            "X-Api-Key": CLIENT_ID, 
            "X-Key": CLIENT_ID, 
            "Content-Type": "application/json", 
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15"
        }
        
        try:
            # Genuine HTTP method structure verified via tracing: PUT
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]:
                    _LOGGER.info("Success! %s state updated to %s.", self._device_name, target_state)
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
                else:
                    resp_text = await response.text()
                    _LOGGER.error("Gardena API rejected property update with status %s: %s", response.status, resp_text)
        except Exception as err: 
            _LOGGER.error("Network error during property tree manipulation: %s", err)

    @property
    def device_info(self): 
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name, "manufacturer": "Gardena (Mocker)"}
