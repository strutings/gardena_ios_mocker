import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, LIGHT_LUX, UnitOfTemperature, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up all available numerical and text-based sensors automatically."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    devices = coordinator.data.get("devices", [])
    for device in devices:
        device_id = device.get("id")
        device_name = device.get("name")
        abilities = device.get("abilities", [])

        for ability in abilities:
            ability_type = ability.get("type")
            properties = ability.get("properties", [])

            for prop in properties:
                prop_name = prop.get("name")
                unit = prop.get("unit")
                
                # Skip binary statuses (these are handled in binary_sensor.py)
                if prop_name in ["connection_status", "emergency_stop", "valve_open"]:
                    continue

                # Define sensor configuration dynamically based on API data
                unit_of_measurement = None
                device_class = None
                icon = None
                entity_category = None

                if unit == "%":
                    unit_of_measurement = PERCENTAGE
                    if "level" in prop_name or "battery" in prop_name:
                        device_class = SensorDeviceClass.BATTERY
                        entity_category = EntityCategory.DIAGNOSTIC
                    else:
                        icon = "mdi:signal"
                elif unit == "C":
                    unit_of_measurement = UnitOfTemperature.CELSIUS
                    device_class = SensorDeviceClass.TEMPERATURE
                elif unit == "lx":
                    unit_of_measurement = LIGHT_LUX
                    device_class = SensorDeviceClass.ILLUMINANCE
                elif unit == "min":
                    unit_of_measurement = "min"
                    device_class = SensorDeviceClass.DURATION
                    icon = "mdi:timer-sand"
                
                # Specific icons for known Gardena states
                if prop_name == "humidity":
                    device_class = SensorDeviceClass.HUMIDITY
                elif prop_name == "status":
                    icon = "mdi:robot-mower"
                elif prop_name == "activity":
                    icon = "mdi:valve"
                elif prop_name in ["version", "serial", "update_state"]:
                    entity_category = EntityCategory.DIAGNOSTIC
                    icon = "mdi:information-outline"

                name_suffix = prop_name.replace("_", " ").title()
                entities.append(
                    GardenaDynamicSensor(
                        coordinator, device_id, device_name, ability_type, 
                        prop_name, name_suffix, unit_of_measurement, device_class, icon, entity_category
                    )
                )

    async_add_entities(entities)


class GardenaDynamicSensor(CoordinatorEntity, SensorEntity):
    """Dynamic sensor for Gardena properties."""

    def __init__(self, coordinator, device_id, device_name, ability_type, prop_name, name_suffix, unit, device_class, icon, entity_category):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._ability_type = ability_type
        self._prop_name = prop_name
        
        self._attr_unique_id = f"{device_id}_{ability_type}_{prop_name}"
        self._attr_name = f"{device_name} {name_suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_entity_category = entity_category

    @property
    def native_value(self):
        """Fetch the value dynamically from the coordinator data."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == self._ability_type:
                        for prop in ability.get("properties", []):
                            if prop.get("name") == self._prop_name:
                                val = prop.get("value")
                                if isinstance(val, dict):
                                    return val.get("main", str(val))
                                return val
        return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }
