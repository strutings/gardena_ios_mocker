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
        
        # 1. GENERATE MOWER SWITCHES
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            if ability.get("type") == "robotic_mower":
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "eco_mode", "Eco Mode", "mdi:leaf", entry))
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "mower_house", "Garage Protection", "mdi:garage-open", entry))
                entities.append(GardenaMowerConfigSwitch(coordinator, device_id, device_name, "frost_sensor", "Frost Sensor (Device)", "mdi:snowflake-alert", entry))
                break

        # 2. GENERATE IRRIGATION SWITCHES
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            if ability.get("type") == "watering":
                _LOGGER.info("Registering irrigation switches for: %s", device_name)
                entities.append(GardenaWateringSwitch(coordinator, device, ability, entry))
                entities.append(GardenaWateringSmartletSwitch(coordinator, device_id, device_name, "smartlet-rain-forecast", "Smartlet Weather Protection", "mdi:cloud-percent", entry))
                entities.append(GardenaWateringSmartletSwitch(coordinator, device_id, device_name, "smartlet-sensor", "Smartlet Soil Moisture Control", "mdi:water-percent", entry))

    async_add_entities(entities)


class GardenaMowerConfigSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle configuration flags on the mower (settings endpoint)."""

    def __init__(self, coordinator, device_id, device_name, config_key, name_suffix, icon, entry) -> None:
        """Initialize the mower config configuration entity."""
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
        """Return True if the option flag configuration is enabled."""
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == self._config_key: 
                        return bool(setting.get("value", False))
        return False

    async def _update_mower_config(self, target_state: bool) -> None:
        """Transmit mower option parameter mutations down to the endpoint server path."""
        manager = self.coordinator.api_manager
        token = manager._token
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
            
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/settings/{setting_id}"
        payload = {"settings": {"name": self._config_key, "value": target_state, "device": self._device_id}}
        headers = {
            "Authorization": f"Bearer {token}", 
            "Authorization-Provider": "husqvarna", 
            "X-Api-Key": CLIENT_ID, 
            "Content-Type": "application/json"
        }
        try:
            async with manager.session.put(url, json=payload, headers=headers, timeout=10) as response:
                if response.status in [200, 202, 204]: 
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err: 
            _LOGGER.error("Error modifying mower switch configuration key %s: %s", self._config_key, err)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._update_mower_config(True)
        
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._update_mower_config(False)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return cross-platform link matching hooks tables."""
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaWateringSmartletSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle cloud-based smartlet modules (Rain or Soil Sensor) with active polling fallback."""

    def __init__(self, coordinator, device_id, device_name, smartlet_key, name_suffix, icon, entry) -> None:
        """Initialize cloud cloud weather or automated soil boundary layers switch."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._smartlet_key = smartlet_key
        self._entry = entry
        
        self._attr_unique_id = f"{device_id}_watering_smartlet_{smartlet_key}"
        self._attr_name = f"{device_name} {name_suffix}"
        self._attr_icon = icon
        self._smartlet_id = f"{self._smartlet_key}_{self._device_id}_1"
        self._live_status = None

    @property
    def should_poll(self) -> bool:
        """Force Home Assistant to evaluate independent background network polling loops updates."""
        return True

    @property
    def is_on(self) -> bool:
        """Return live status boolean flag parsed from cloud data graphs streams."""
        if self._live_status is not None:
            return self._live_status

        data = self.coordinator.data
        smartlets = data.get("smartlets", data.get("data", [])) if isinstance(data, dict) else []
        for s in smartlets:
            if isinstance(s, dict) and s.get("id") == self._smartlet_id:
                return bool(s.get("attributes", {}).get("enabled", False))
        return False

    async def async_update(self) -> None:
        """Fetch fresh live status parameters directly from verified standalone smartlet endpoint."""
        manager = self.coordinator.api_manager
        token = manager._token
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
                    
                    if self._smartlet_key == "smartlet-rain-forecast":
                        threshold = float(attributes.get("millimeters-threshold", 10.0))
                        self.hass.data[DOMAIN][f"{self._device_id}_rain_threshold"] = threshold
                    elif self._smartlet_key == "smartlet-sensor":
                        threshold = float(attributes.get("threshold", 50.0))
                        self.hass.data[DOMAIN][f"{self._device_id}_soil_threshold"] = threshold
                        
                    _LOGGER.debug("Gardena live smartlet update for %s (%s): enabled=%s", self._device_name, self._smartlet_key, enabled_state)
        except Exception as err:
            _LOGGER.debug("Live polling failed for smartlet %s (%s): %s", self._device_name, self._smartlet_key, err)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the smartlet module switch on."""
        await self._update_smartlet(True)
        
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the smartlet module switch off."""
        await self._update_smartlet(False)

    async def _update_smartlet(self, enable: bool) -> None:
        """Transmit specialized payload trees blocks to matching structural layout endpoints models mappings."""
        manager = self.coordinator.api_manager
        token = manager._token
        location_id = self._entry.data["location_id"]
        
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets/{self._smartlet_id}"
        
        attributes_payload = {
            "valve": 1,
            "available": True,
            "enabled": enable,
            "scope": "valve"
        }
        
        # Dynamically locate soil moisture sensor reference ID linking maps properties table index variables hooks
        sensor_device_id = None
        devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
        for d in devices:
            if isinstance(d, dict) and d.get("category") == "sensor":
                sensor_device_id = d.get("id")
                break
        if not sensor_device_id:
            sensor_device_id = "6b3936af-cc29-4008-882b-56f04c9928a1"

        relationships_payload = {
            "owner": { "data": { "type": "device", "id": str(self._device_id) } },
            "location": { "data": { "type": "location", "id": str(location_id) } }
        }

        if self._smartlet_key == "smartlet-rain-forecast":
            threshold = self.hass.data[DOMAIN].get(f"{self._device_id}_rain_threshold", 10.0)
            attributes_payload["millimeters-threshold"] = float(threshold)
        elif self._smartlet_key == "smartlet-sensor":
            threshold = self.hass.data[DOMAIN].get(f"{self._device_id}_soil_threshold", 50.0)
            attributes_payload["threshold"] = int(threshold)
            relationships_payload["sensor"] = {
                "data": { "type": "device", "id": str(sensor_device_id) } if enable else None
            }

        payload = {
            "data": {
                "attributes": attributes_payload,
                "relationships": relationships_payload,
                "type": str(self._smartlet_key)
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
                if response.status in [200, 202, 204]:
                    self._live_status = enable
                    self.async_write_ha_state()
                    self.hass.async_create_task(self.coordinator.async_request_refresh())
        except Exception as err:
            _LOGGER.error("Failed to update watering smartlet %s: %s", self._smartlet_key, err)

    @property
    def device_info(self) -> dict[str, Any]:
        """Link matching context maps elements branches strings pointers identifiers table arrays."""
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name}


class GardenaWateringSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to start and stop valve irrigation loops channels manually."""

    def __init__(self, coordinator, device, ability, entry) -> None:
        """Initialize raw physical valve trigger component mapping switch variables attributes handles."""
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._device_name = device.get("name")
        self._entry = entry
        
        self._attr_unique_id = f"{self._device_id}_watering_switch"
        self._attr_name = f"{device.get('name')} Irrigation"
        self._attr_icon = "mdi:water-pump"

    @property
    def is_on(self) -> bool:
        """Return True if valve state machine reflects active state properties structures blocks."""
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
        """Fetch preset sliders minutes durations limits and open valve loop array straight away."""
        duration_min = self.hass.data[DOMAIN].get(f"{self._device_id}_duration", 15)
        duration_sec = int(duration_min * 60)
        await self._send_watering_property_update("manual", duration_sec)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Force current opened valve iteration loop back down onto idle state boundaries configuration structures maps."""
        await self._send_watering_property_update("idle", 0)

    async def _send_watering_property_update(self, target_state: str, duration_sec: int) -> None:
        """Transmit raw valve state matrix attributes straight into properties trees maps layers nodes tables."""
        manager = self.coordinator.api_manager
        token = manager._token
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
                    devices = self.coordinator.data.get("devices", []) if isinstance(self.coordinator.data, dict) else []
                    for d in devices:
                        if isinstance(d, dict) and d.get("id") == self._device_id:
                            for ability in d.get("abilities", []):
                                if isinstance(ability, dict) and ability.get("type") == "watering":
                                    for prop in ability.get("properties", []):
                                        if isinstance(prop, dict) and prop.get("name") == "watering_timer_1":
                                            prop["value"] = {"state": target_state, "duration": duration_sec, "valve_id": 1}
                                            break
                    self.async_write_ha_state()
                    self.hass.async_create_task(self.coordinator.async_refresh())
        except Exception as err: 
            _LOGGER.error("Network error executing valve iteration parameter state adjustment tree update: %s", err)

    @property
    def device_info(self) -> dict[str, Any]:
        """Link matching context platform tracking metadata elements hooks arrays markers nodes descriptors tables blocks."""
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name, "manufacturer": "Gardena (Mocker)"}
