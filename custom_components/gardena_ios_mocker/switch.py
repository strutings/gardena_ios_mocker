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

    devices = coordinator.data.get("devices", []) if isinstance(coordinator.data, dict) else []
    for device in devices:
        if not isinstance(device, dict):
            continue
            
        device_id = device.get("id")
        device_name = device.get("name")
        abilities = device.get("abilities", [])
        
        # 1. Generate mower configuration switches
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            if ability.get("type") == "robotic_mower":
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "eco_mode", "mdi:leaf", entry))
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "mower_house", "mdi:garage-open", entry))
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "frost_sensor", "mdi:snowflake-alert", entry))
                
                # Sjekker og genererer Corridor Cut-brytere for aktive startpunkter (Indeks 0, 1, 2)
                for setting in device.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "starting_points":
                        points_list = setting.get("value", [])
                        for idx, point in enumerate(points_list):
                            if isinstance(point, dict) and point.get("enabled", False):
                                entities.append(GardenaMowerCorridorCutSwitch(coordinator, device_id, device_name, idx, entry))
                break

        # 2. Generate irrigation control switches
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            if ability.get("type") == "watering":
                _LOGGER.info("Registering irrigation switches for device: %s", device_name)
                entities.append(GardenaWateringSwitch(coordinator, device, ability, entry))
                entities.append(GardenaWateringSmartletSwitch(coordinator, device_id, device_name, "smartlet_rain_forecast", "mdi:cloud-percent", entry))
                entities.append(GardenaWateringSmartletSwitch(coordinator, device_id, device_name, "smartlet_sensor", "mdi:water-percent", entry))

    async_add_entities(entities)


class GardenaMowerCorridorCutSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle Corridor Cut on a specific starting point index branch."""

    has_entity_name = False

    def __init__(self, coordinator, device_id, device_name, index, entry) -> None:
        """Initialize the corridor cut toggle branch."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._index = index
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_mower_corridor_cut_point_{index}"
        self._attr_name = f"{device_name} Starting Point {index + 1} Corridor Cut"
        self._attr_icon = "mdi:scissors-cutting"

    @property
    def is_on(self) -> bool:
        """Return true if corridor cut is enabled for this specific starting point."""
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "starting_points":
                        points_list = setting.get("value", [])
                        if len(points_list) > self._index:
                            return bool(points_list[self._index].get("corridor_cut_enabled", False))
        return False

    async def _update_corridor_cut(self, target_state: bool) -> None:
        """Mutate specific corridor cut element index array map leaf node."""
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        current_points = []
        setting_id = None
        
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "starting_points":
                        current_points = list(setting.get("value", []))
                        setting_id = setting.get("id")
                        break
                        
        if not setting_id or len(current_points) <= self._index:
            return
            
        current_points[self._index]["corridor_cut_enabled"] = target_state
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/settings/{setting_id}?locationId={location_id}"
        payload = {"settings": {"name": "starting_points", "value": current_points, "device": self._device_id}}
        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "Content-Type": "application/json"
        }
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status == 401:
                    token = await manager.async_authenticate()
                    headers["Authorization"] = f"Bearer {token}"
                    await manager.session.put(url, json=payload, headers=headers, timeout=10)
                elif response.status in [200, 202, 204]: 
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err:
            _LOGGER.error("Failed to alter corridor cut layout index %s matrix: %s", self._index, err)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._update_corridor_cut(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._update_corridor_cut(False)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaMowerConfigSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle configuration flags on the mower (settings endpoint)."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, config_key, icon, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._config_key = config_key
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_mower_switch_{config_key}_real_api"
        self._attr_translation_key = config_key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == self._config_key: 
                        return bool(setting.get("value", False))
        return False

    async def _update_mower_config(self, target_state: bool) -> None:
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        setting_id = None
        
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == self._config_key: 
                        setting_id = setting.get("id")
                        break
                        
        if not setting_id: 
            _LOGGER.error("Failed to find setting_id for configuration key: %s", self._config_key)
            return
            
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/settings/{setting_id}?locationId={location_id}"
        payload = {"settings": {"name": self._config_key, "value": target_state, "device": self._device_id}}
        headers = {
            "Authorization": f"Bearer {token}", 
            "Authorization-Provider": "husqvarna", 
            "X-Api-Key": CLIENT_ID, 
            "Content-Type": "application/json"
        }
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status == 401:
                    token = await manager.async_authenticate()
                    headers["Authorization"] = f"Bearer {token}"
                    async with manager.session.put(url, json=payload, headers=headers, timeout=10) as retry_resp:
                        if retry_resp.status in [200, 202, 204]:
                            self.hass.async_create_task(self.coordinator.async_request_refresh())
                elif response.status in [200, 202, 204]: 
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err: 
            _LOGGER.error("Error modifying mower configuration key %s: %s", self._config_key, err)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._update_mower_config(True)
        
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._update_mower_config(False)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaWateringSmartletSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle cloud-based smartlet modules (Rain or Soil Sensor) with active polling fallback."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, smartlet_key, icon, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._smartlet_key = smartlet_key
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_watering_smartlet_{smartlet_key}"
        self._attr_translation_key = smartlet_key
        self._attr_icon = icon
        
        api_key = smartlet_key.replace("_", "-")
        self._smartlet_id = f"{api_key}_{self._device_id}_1"
        self._live_status = None

    @property
    def should_poll(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        if self._live_status is not None:
            return self._live_status

        data = self.coordinator.data
        smartlets = data.get("smartlets", data.get("data", [])) if isinstance(data, dict) else []
        for s in smartlets:
            if isinstance(s, dict) and s.get("id") == self._smartlet_id:
                return bool(s.get("attributes", {}).get("enabled", False))
        return False

    async def async_update(self) -> None:
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets/{self._smartlet_id}"
        headers = {
            "Authorization": f"Bearer {token}", 
            "Authorization-Provider": "husqvarna", 
            "X-Api-Key": CLIENT_ID, 
            "X-Key": CLIENT_ID
        }
        
        try:
            async with manager.session.get(url, headers=headers, timeout=5) as response:
                if response.status == 200:
                    res_json = await response.json()
                    attributes = res_json.get("data", {}).get("attributes", {})
                    enabled_state = bool(attributes.get("enabled", False))
                    self._live_status = enabled_state
        except Exception as err:
            _LOGGER.debug("Live polling failed for smartlet %s: %s", self._device_name, err)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._update_smartlet(True)
        
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._update_smartlet(False)

    async def _update_smartlet(self, enable: bool) -> None:
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets/{self._smartlet_id}"
        
        attributes_payload = {"valve": 1, "available": True, "enabled": enable, "scope": "valve"}
        sensor_device_id = "6b3936af-cc29-4008-882b-56f04c9928a1"
        relationships_payload = {
            "owner": { "data": { "type": "device", "id": str(self._device_id) } },
            "location": { "data": { "type": "location", "id": str(location_id) } }
        }

        api_type_key = self._smartlet_key.replace("_", "-")
        payload = {"data": {"attributes": attributes_payload, "relationships": relationships_payload, "type": str(api_type_key)}}
        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
            "Content-Type": "application/json"
        }
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]:
                    self._live_status = enable
                    self.async_write_ha_state()
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err:
            _LOGGER.error("Failed to update watering smartlet %s: %s", self._smartlet_key, err)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaWateringSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to start and stop valve irrigation loops channels manually."""

    has_entity_name = True

    def __init__(self, coordinator, device, ability, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._entry = entry
        
        self._attr_unique_id = f"{self._device_id}_watering_switch"
        self._attr_translation_key = "watering_switch"
        self._attr_icon = "mdi:water-pump"

    @property
    def is_on(self) -> bool:
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if isinstance(ability, dict) and ability.get("type") == "watering":
                        for prop in ability.get("properties", []):
                            if isinstance(prop, dict) and prop.get("name") == "watering_timer_1":
                                val = prop.get("value", {})
                                if isinstance(val, dict):
                                    return str(val.get("state", "")).lower() in ["watering", "manual", "valve_open", "active"]
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        duration_min = self.hass.data[DOMAIN].get(f"{self._device_id}_duration", 15)
        duration_sec = int(duration_min * 60)
        await self._send_watering_property_update("manual", duration_sec)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send_watering_property_update("idle", 0)

    async def _send_watering_property_update(self, target_state: str, duration_sec: int) -> None:
        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/abilities/watering/properties/watering_timer_1?locationId={location_id}"
        payload = {"properties": {"name": "watering_timer_1", "value": {"state": target_state, "duration": duration_sec, "valve_id": 1}}}
        headers = {
            "Authorization": f"Bearer {token}", 
            "Authorization-Provider": "husqvarna", 
            "X-Api-Key": CLIENT_ID, 
            "Content-Type": "application/json"
        }
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]:
                    self.hass.async_create_task(self.coordinator.async_refresh())
        except Exception as err: 
            _LOGGER.error("Network error executing valve iteration parameter state adjustment tree update: %s", err)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name, "manufacturer": "Gardena (Mocker)"}
