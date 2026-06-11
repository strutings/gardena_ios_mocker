import logging
from typing import Any
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up number configurations for mower and irrigation devices."""
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
                
            ability_type = ability.get("type")

            if ability_type == "robotic_mower":
                entities.append(GardenaMowerConfigNumber(coordinator, device_id, device_name, "drive_past_wire", 1, 50, 1, "cm", "mdi:arrow-expand-horizontal", entry))
                entities.append(GardenaMowerConfigNumber(coordinator, device_id, device_name, "starting_distance", 0.2, 3.0, 0.1, "m", "mdi:map-marker-distance", entry))
                
                for i in range(3):
                    entities.append(GardenaMowerPointNumber(coordinator, device_id, device_name, i, "distance_in_meters", 0, 500, "m", "mdi:ray-start-arrow", entry))
                    entities.append(GardenaMowerPointNumber(coordinator, device_id, device_name, i, "probability_in_percent", 0, 100, "%", "mdi:percent", entry))

            elif ability_type == "watering":
                if f"{device_id}_duration" not in hass.data[DOMAIN]:
                    hass.data[DOMAIN][f"{device_id}_duration"] = 15
                if f"{device_id}_rain_threshold" not in hass.data[DOMAIN]:
                    hass.data[DOMAIN][f"{device_id}_rain_threshold"] = 10.0
                if f"{device_id}_soil_threshold" not in hass.data[DOMAIN]:
                    hass.data[DOMAIN][f"{device_id}_soil_threshold"] = 50.0
                    
                entities.append(GardenaIrrigationTime(coordinator, device, ability, entry))
                entities.append(GardenaRainThresholdNumber(coordinator, device_id, device_name, entry))
                entities.append(GardenaSoilThresholdNumber(coordinator, device_id, device_name, entry))

    async_add_entities(entities)


class GardenaMowerConfigNumber(CoordinatorEntity, NumberEntity):
    """Numerical configuration flag modifier settings for robotic mowers."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, config_key, min_val, max_val, step, unit, icon, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._config_key = config_key
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_mower_number_{config_key}_real_api"
        self._attr_translation_key = config_key
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == self._config_key: 
                        return float(setting.get("value", 0))
        return None

    # NYTT: Legger til kalkulert undertekst/info direkte som en attributt på avstands-slideren!
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return dynamic attributes including charging station proportion if this is starting_distance."""
        if self._config_key != "starting_distance":
            return None
            
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "starting_points":
                        points_list = setting.get("value", [])
                        total_remote_pct = 0
                        for point in points_list:
                            if isinstance(point, dict):
                                total_remote_pct += int(point.get("probability_in_percent", 0))
                        
                        return {
                            "charging_station_proportion": f"{max(0, 100 - total_remote_pct)}%",
                            "friendly_info": f"{max(0, 100 - total_remote_pct)}% started from charging station"
                        }
        return {"charging_station_proportion": "100%"}

    async def async_set_native_value(self, value: float) -> None:
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
            return
            
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/settings/{setting_id}?locationId={location_id}"
        payload_val = float(value) if self._config_key == "starting_distance" else int(value)
        payload = {"settings": {"name": self._config_key, "value": payload_val, "device": self._device_id}}
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
            _LOGGER.error("Error modifying configuration key %s: %s", self._config_key, err)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaMowerPointNumber(CoordinatorEntity, NumberEntity):
    """Numerical entity modifier to adjust specific starting points navigation variables."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, index, sub_key, min_val, max_val, unit, icon, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._index = index
        self._sub_key = sub_key
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_mower_point_{index}_{sub_key}_real_api"
        self._attr_translation_key = sub_key
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "starting_points":
                        points_list = setting.get("value", [])
                        if len(points_list) > self._index:
                            return float(points_list[self._index].get(self._sub_key, 0))
        return None

    async def async_set_native_value(self, value: float) -> None:
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
            
        current_points[self._index][self._sub_key] = int(value)
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
            _LOGGER.error("Error updating starting point configuration mapping matrix: %s", err)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaIrrigationTime(CoordinatorEntity, NumberEntity):
    """Numerical configuration entity to adjust global manual valve irrigation target durations."""

    has_entity_name = True

    def __init__(self, coordinator, device, ability, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._entry = entry
        
        self._attr_unique_id = f"{self._device_id}_irrigation_time"
        self._attr_translation_key = "irrigation_time"
        self._attr_icon = "mdi:clock-outline"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 90
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float:
        return float(self.hass.data[DOMAIN].get(f"{self._device_id}_duration", 15))

    async def async_set_native_value(self, value: float) -> None:
        self.hass.data[DOMAIN][f"{self._device_id}_duration"] = int(value)
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaRainThresholdNumber(CoordinatorEntity, NumberEntity):
    """Slider interface modifier component mapping directly into smartlet cloud weather precipitation bounds layers."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_smartlet_rain_threshold"
        self._attr_translation_key = "smartlet_rain_threshold"
        self._attr_icon = "mdi:water-percent"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 10
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "mm"
        self._attr_mode = NumberMode.SLIDER
        self._smartlet_id = f"smartlet-rain-forecast_{self._device_id}_1"

    @property
    def native_value(self) -> float:
        return float(self.hass.data[DOMAIN].get(f"{self._device_id}_rain_threshold", 10.0))

    async def async_set_native_value(self, value: float) -> None:
        self.hass.data[DOMAIN][f"{self._device_id}_rain_threshold"] = float(value)
        self.async_write_ha_state()

        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets/{self._smartlet_id}"
        
        is_enabled = True
        smartlet_entity = self.hass.states.get(f"switch.{self._device_name.lower().replace(' ', '_')}_smartlet_weather_protection")
        if smartlet_entity:
            is_enabled = (smartlet_entity.state == "on")

        payload = {
            "data": {
                "attributes": {
                    "valve": 1,
                    "available": True,
                    "enabled": is_enabled,
                    "scope": "valve",
                    "millimeters-threshold": float(value)
                },
                "relationships": {
                    "owner": { "data": { "type": "device", "id": str(self._device_id) } },
                    "location": { "data": { "type": "location", "id": str(location_id) } }
                },
                "type": "smartlet-rain-forecast"
            }
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
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
            _LOGGER.error("Failed to update rain weather cutoff parameter threshold matrix for %s: %s", self._device_name, err)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaSoilThresholdNumber(CoordinatorEntity, NumberEntity):
    """Slider controller parameter mapping bounds directly down onto the physical smartlet sensor array systems endpoints."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, entry) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_smartlet_soil_threshold"
        self._attr_translation_key = "smartlet_soil_threshold"
        self._attr_icon = "mdi:water-percent"
        self._attr_native_min_value = 5
        self._attr_native_max_value = 100
        self._attr_native_step = 5
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.SLIDER
        self._smartlet_id = f"smartlet-sensor_{self._device_id}_1"

    @property
    def native_value(self) -> float:
        return float(self.hass.data[DOMAIN].get(f"{self._device_id}_soil_threshold", 50.0))

    async def async_set_native_value(self, value: float) -> None:
        self.hass.data[DOMAIN][f"{self._device_id}_soil_threshold"] = float(value)
        self.async_write_ha_state()

        manager = self.coordinator.api_manager
        token = await manager.async_authenticate() if not manager._token else manager._token
        location_id = self._entry.data["location_id"]
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets/{self._smartlet_id}"
        
        is_enabled = True
        smartlet_entity = self.hass.states.get(f"switch.{self._device_name.lower().replace(' ', '_')}_smartlet_soil_moisture_control")
        if smartlet_entity:
            is_enabled = (smartlet_entity.state == "on")

        sensor_device_id = None
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("category") == "sensor":
                sensor_device_id = d.get("id")
                break
        if not sensor_device_id:
            sensor_device_id = "6b3936af-cc29-4008-882b-56f04c9928a1"

        payload = {
            "data": {
                "attributes": {
                    "valve": 1,
                    "available": True,
                    "enabled": is_enabled,
                    "scope": "valve",
                    "threshold": int(value)
                },
                "relationships": {
                    "owner": { "data": { "type": "device", "id": str(self._device_id) } },
                    "location": { "data": { "type": "location", "id": str(location_id) } },
                    "sensor": { "data": { "type": "device", "id": str(sensor_device_id) } if is_enabled else None }
                },
                "type": "smartlet-sensor"
            }
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
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
            _LOGGER.error("Failed to update soil moisture target cutoff metric threshold parameter value settings for %s: %s", self._device_name, err)

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}
