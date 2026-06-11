import logging
from typing import Any
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up select entities for Gardena smartlets."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    devices = coordinator.data.get("devices", []) if isinstance(coordinator.data, dict) else []
    for device in devices:
        if not isinstance(device, dict):
            continue
            
        device_id = device.get("id")
        device_name = device.get("name")
        abilities = device.get("abilities", [])
        
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            if ability.get("type") == "robotic_mower":
                entities.append(GardenaMowerSensorControlSelect(coordinator, device_id, device_name, entry))
                break

    async_add_entities(entities)


class GardenaMowerSensorControlSelect(CoordinatorEntity, SelectEntity):
    """Select entity to control Gardena SensorControl cloud smartlet levels and activation state."""

    def __init__(self, coordinator: Any, device_id: str, device_name: str, entry: ConfigEntry) -> None:
        """Initialize the robotic mower growth sensitivity level select control entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_smartlet_sensor_control"
        self._attr_name = f"{device_name} SensorControl"
        self._attr_icon = "mdi:grass"
        self._attr_options = ["Off", "Low", "Medium", "High"]
        
        self._state_override = None

    @property
    def current_option(self) -> str | None:
        """Return the current selected growth sensor sensitivity level or Off from coordinator device settings cache."""
        if self._state_override is not None:
            return self._state_override

        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for device in devices:
            if isinstance(device, dict) and device.get("id") == self._device_id:
                settings = device.get("settings", [])
                for setting in settings:
                    if isinstance(setting, dict) and setting.get("name") == "sensor_control":
                        value_dict = setting.get("value", {})
                        if not value_dict.get("enabled", False):
                            return "Off"
                        
                        # Validated API map scale values from HAR streams analysis: 2=Low, 3=Medium, 4=High
                        level = value_dict.get("level", 3)
                        if level == 2:
                            return "Low"
                        if level == 3:
                            return "Medium"
                        if level == 4:
                            return "High"
                break

        return "Off"

    async def async_select_option(self, option: str) -> None:
        """Change the current sensitivity level or disable the cloud smartlet using verified replication."""
        manager = self.coordinator.api_manager
        token = manager._token
        location_id = self._entry.data["location_id"]
        
        smartlet_id = f"smartlet-sensor-control-mower_{self._device_id}"
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets/{smartlet_id}"
        level_map = {"Low": 2, "Medium": 3, "High": 4}
        
        # Retrieve previous state configurations to act as alternative fallback metric boundaries
        current_level = 3
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for device in devices:
            if isinstance(device, dict) and device.get("id") == self._device_id:
                for setting in device.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "sensor_control":
                        current_level = setting.get("value", {}).get("level", 3)
                        break

        target_level = level_map.get(option, current_level)
        is_enabled = (option != "Off")

        payload = {
            "data": {
                "attributes": {
                    "level": int(target_level),
                    "available": True,
                    "enabled": is_enabled,
                    "scope": "device"
                },
                "relationships": {
                    "owner": {
                        "data": {
                            "type": "device",
                            "id": str(self._device_id)
                        }
                    }
                },
                "type": "smartlet-sensor-control-mower"
            }
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]:
                    _LOGGER.info("Successfully transmitted SensorControl state: %s (API level: %s)", option, target_level)
                    
                    # Temporarily lock state override flags so local UI rendering prevents bouncy jumps during commit cycles
                    self._state_override = option
                    
                    # Directly update the local state model dictionary maps memory array tree indices maps instantly
                    for device in devices:
                        if isinstance(device, dict) and device.get("id") == self._device_id:
                            for setting in device.get("settings", []):
                                if isinstance(setting, dict) and setting.get("name") == "sensor_control":
                                    setting["value"] = {"enabled": is_enabled, "level": target_level}
                                    break

                    self.async_write_ha_state()
                    
                    # Unlock temporary localized flags layout and request silent global state tree tracking refreshes
                    self._state_override = None
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
                else:
                    response_text = await response.text()
                    _LOGGER.error("Gardena infrastructure endpoint rejected SensorControl parameter updates with status %s: %s", response.status, response_text)
        except Exception as err:
            _LOGGER.error("Network exception intercepted during transmission of SensorControl options maps packet payload trees: %s", err)

    @property
    def device_info(self) -> dict[str, Any]:
        """Link identifiers targeting down across matching node clusters branches trees elements platforms tables."""
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}
