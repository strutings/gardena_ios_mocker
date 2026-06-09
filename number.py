import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up number configurations for mower and irrigation duration."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    devices = coordinator.data.get("devices", [])
    for device in devices:
        device_id = device.get("id")
        device_name = device.get("name")
        abilities = device.get("abilities", [])

        for ability in abilities:
            ability_type = ability.get("type")

            if ability_type == "robotic_mower":
                entities.append(GardenaMowerConfigNumber(coordinator, device_id, device_name, "drive_past_wire", "Drive Past Wire", 1, 50, "cm", "mdi:arrow-expand-horizontal", entry))
                entities.append(GardenaMowerConfigNumber(coordinator, device_id, device_name, "starting_distance", "Remote Start Distance", 0, 500, "m", "mdi:map-marker-distance", entry))
                
                for i in range(3):
                    entities.append(GardenaMowerPointNumber(coordinator, device_id, device_name, i, "distance_in_meters", f"Starting Point {i+1} Distance", 0, 500, "m", "mdi:ray-start-arrow", entry))
                    entities.append(GardenaMowerPointNumber(coordinator, device_id, device_name, i, "probability_in_percent", f"Starting Point {i+1} Proportion", 0, 100, "%", "mdi:percent", entry))

            # Handle the watering ability configuration for the irrigation timer
            elif ability_type == "watering":
                _LOGGER.info("Creating irrigation duration number entity for %s", device_name)
                entities.append(GardenaIrrigationTime(coordinator, device, ability))

    async_add_entities(entities)


class GardenaMowerConfigNumber(CoordinatorEntity, NumberEntity):
    """Numerical setting for Drive Past Wire and Remote Start Distance."""
    def __init__(self, coordinator, device_id, device_name, config_key, name_suffix, min_val, max_val, unit, icon, entry):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._config_key = config_key
        self._entry = entry
        self._attr_unique_id = f"{device_id}_mower_number_{config_key}_real_api"
        self._attr_name = f"{device_name} {name_suffix}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if setting.get("name") == self._config_key: return float(setting.get("value", 0))
        return None

    async def async_set_native_value(self, value: float) -> None:
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
        payload = {"settings": {"name": self._config_key, "value": int(value), "device": self._device_id}}
        headers = {"Authorization": f"Bearer {token}", "Authorization-Provider": "husqvarna", "X-Api-Key": CLIENT_ID, "Content-Type": "application/json"}
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]: self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err: _LOGGER.error("Error modifying value %s: %s", self._config_key, err)

    @property
    def device_info(self): return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaMowerPointNumber(CoordinatorEntity, NumberEntity):
    """Numerical setting for individual remote starting points."""
    def __init__(self, coordinator, device_id, device_name, index, sub_key, name_suffix, min_val, max_val, unit, icon, entry):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._index = index
        self._sub_key = sub_key
        self._entry = entry
        self._attr_unique_id = f"{device_id}_mower_point_{index}_{sub_key}_real_api"
        self._attr_name = f"{device_name} {name_suffix}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if setting.get("name") == "starting_points":
                        points_list = setting.get("value", [])
                        if len(points_list) > self._index:
                            return float(points_list[self._index].get(self._sub_key, 0))
        return None

    async def async_set_native_value(self, value: float) -> None:
        manager = self.coordinator.api_manager
        token = manager._token
        location_id = self._entry.data["location_id"]
        current_points = []
        setting_id = None
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if setting.get("name") == "starting_points":
                        current_points = list(setting.get("value", []))
                        setting_id = setting.get("id")
                        break
        if not setting_id or len(current_points) <= self._index: return
        current_points[self._index][self._sub_key] = int(value)
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._device_id}/settings/{setting_id}?locationId={location_id}"
        payload = {"settings": {"name": "starting_points", "value": current_points, "device": self._device_id}}
        headers = {"Authorization": f"Bearer {token}", "Authorization-Provider": "husqvarna", "X-Api-Key": CLIENT_ID, "Content-Type": "application/json"}
        try:
            async with manager.session.post(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]: self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err: _LOGGER.error("Error updating starting point: %s", err)

    @property
    def device_info(self): return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaIrrigationTime(CoordinatorEntity, NumberEntity):
    """Numerical configuration entity to adjust manual irrigation duration."""

    def __init__(self, coordinator, device, ability):
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._ability_id = "watering"
        
        self._attr_unique_id = f"{self._device_id}_irrigation_time"
        self._attr_name = f"{self._device_name} Irrigation Duration"
        self._attr_icon = "mdi:clock-outline"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 180
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float:
        """Safely extracts the duration from the physical dictionary parsed from the HAR log stream."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                # Verifies 'manual_watering_button' configuration states (reporting 1200 / 1800 seconds)
                for ability in d.get("abilities", []):
                    if ability.get("type") == "manual_watering_button":
                        for prop in ability.get("properties", []):
                            if prop.get("name") == "button_config_time":
                                sec = prop.get("value", 1800)
                                minutes = int(sec / 60)
                                self.hass.data[DOMAIN][f"{self._device_id}_irrigation_time"] = minutes
                                return float(minutes)
                                        
        return float(self.hass.data[DOMAIN].get(f"{self._device_id}_irrigation_time", 30))

    async def async_set_native_value(self, value: float) -> None:
        """Stores the desired minute value locally in HA state memory for usage by the activation switch."""
        self.hass.data[DOMAIN][f"{self._device_id}_irrigation_time"] = int(value)
        self.async_write_ha_state()

    @property
    def device_info(self): return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name, "manufacturer": "Gardena (Mocker)"}
