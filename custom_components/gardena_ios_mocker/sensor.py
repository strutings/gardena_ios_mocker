import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import PERCENTAGE, LIGHT_LUX, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up all available numerical, text-based, and calculated sensors automatically."""
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

                # Define sensor configuration dynamically based on API data schemas
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
                
                # Assign specific diagnostic entity categories
                if prop_name in ["version", "serial", "update_state", "initialized"]:
                    entity_category = EntityCategory.DIAGNOSTIC

                # Set specific icons/classes for known telemetry keys
                if prop_name == "humidity":
                    device_class = SensorDeviceClass.HUMIDITY
                elif prop_name == "status":
                    icon = "mdi:robot-mower"
                elif prop_name == "activity":
                    icon = "mdi:valve"
                
                # Handle the specific 'timestamp_next_start' property natively as a Timestamp object
                elif prop_name == "timestamp_next_start":
                    device_class = SensorDeviceClass.TIMESTAMP
                    icon = "mdi:calendar-clock"

                # Generate a clean fallback name from the property key string
                if prop_name == "timestamp_next_start":
                    fallback_name = "Next Start Time"
                else:
                    fallback_name = prop_name.replace("_", " ").title()

                entities.append(
                    GardenaDynamicSensor(
                        coordinator, device_id, device_name, ability_type, 
                        prop_name, fallback_name, unit_of_measurement, device_class, icon, entity_category
                    )
                )

                # Inject secondary calculated sensor: Countdown duration until full charge
                if prop_name == "timestamp_next_start":
                    entities.append(
                        GardenaTimeToFullChargeSensor(
                            coordinator, device_id, device_name, ability_type
                        )
                    )

    async_add_entities(entities)


class GardenaDynamicSensor(CoordinatorEntity, SensorEntity):
    """Dynamic sensor for monitoring individual Gardena telemetry properties."""

    has_entity_name = False

    def __init__(self, coordinator, device_id, device_name, ability_type, prop_name, fallback_name, unit, device_class, icon, entity_category):
        """Initialize the dynamic telemetry sensor instance."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._ability_type = ability_type
        self._prop_name = prop_name
        
        self._attr_unique_id = f"{device_id}_{ability_type}_{prop_name}"
        self._attr_name = f"{device_name} {fallback_name}"
        
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_entity_category = entity_category

    @property
    def native_value(self):
        """Fetch the value dynamically from the coordinator data cache."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == self._ability_type:
                        for prop in ability.get("properties", []):
                            if prop.get("name") == self._prop_name:
                                val = prop.get("value")
                                if isinstance(val, dict):
                                    val = val.get("main", str(val))
                                
                                # Enforce proper ISO parsing to adapt raw UTC strings into local user timezones
                                if self._attr_device_class == SensorDeviceClass.TIMESTAMP and val:
                                    try:
                                        return dt_util.parse_datetime(str(val))
                                    except Exception:
                                        return val
                                return val
        return None

    @property
    def device_info(self):
        """Return cross-platform link pointers attaching entities to their master device entry."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }


class GardenaTimeToFullChargeSensor(CoordinatorEntity, SensorEntity):
    """Calculated countdown sensor showing remaining duration until full charge / next start."""

    has_entity_name = False

    def __init__(self, coordinator, device_id, device_name, ability_type):
        """Initialize the countdown duration sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._ability_type = ability_type
        
        self._attr_unique_id = f"{device_id}_{ability_type}_time_to_full_charge"
        self._attr_name = f"{device_name} Time To Full Charge"
        
        self._attr_native_unit_of_measurement = "min"
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_icon = "mdi:battery-clock"

    @property
    def native_value(self) -> float | None:
        """Calculate minutes remaining between now and the scheduled next start timestamp."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == self._ability_type:
                        for prop in ability.get("properties", []):
                            if prop.get("name") == "timestamp_next_start":
                                val = prop.get("value")
                                if isinstance(val, dict):
                                    val = val.get("main", str(val))
                                
                                if not val:
                                    return None
                                    
                                try:
                                    target_time = dt_util.parse_datetime(str(val))
                                    if not target_time:
                                        return None
                                        
                                    now = dt_util.now()
                                    diff = target_time - now
                                    minutes_remaining = int(diff.total_seconds() / 60)
                                    
                                    # If the target start timestamp is in the past, return 0 minutes left
                                    return max(0, minutes_remaining)
                                except Exception:
                                    return None
        return None

    @property
    def device_info(self):
        """Link this calculated sensor onto the same physical mower device card."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }
