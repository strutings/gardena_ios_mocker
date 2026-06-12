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
        if not isinstance(device, dict):
            continue
            
        device_id = device.get("id")
        device_name = device.get("name")
        abilities = device.get("abilities", [])

        # Sørger for at kalkulert sensor registreres uansett for enheten
        entities.append(GardenaChargingStationProportionSensor(coordinator, device_id, device_name))

        for ability in abilities:
            ability_type = ability.get("type")
            properties = ability.get("properties", [])
            
            for prop in properties:
                prop_name = prop.get("name")
                unit = prop.get("unit")
                
                if prop_name in ["connection_status", "emergency_stop", "valve_open"]:
                    continue

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
                
                if prop_name in ["version", "serial", "update_state", "initialized"]:
                    entity_category = EntityCategory.DIAGNOSTIC

                if prop_name == "humidity":
                    device_class = SensorDeviceClass.HUMIDITY
                elif prop_name == "status":
                    icon = "mdi:robot-mower"
                elif prop_name == "activity":
                    icon = "mdi:valve"
                elif prop_name == "timestamp_next_start":
                    device_class = SensorDeviceClass.TIMESTAMP
                    icon = "mdi:calendar-clock"

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

                if prop_name == "timestamp_next_start":
                    entities.append(GardenaTimeToFullChargeSensor(coordinator, device_id, device_name, ability_type))

    async_add_entities(entities)


class GardenaChargingStationProportionSensor(CoordinatorEntity, SensorEntity):
    """Calculates 100 - sum of remote starting points percentages."""

    has_entity_name = False

    def __init__(self, coordinator, device_id, device_name):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_charging_station_proportion"
        self._attr_name = f"{device_name} Starting Point Charging Station Proportion"
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:ev-station"

    @property
    def native_value(self) -> int | None:
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if isinstance(d, dict) and d.get("id") == self._device_id:
                for setting in d.get("settings", []):
                    if isinstance(setting, dict) and setting.get("name") == "starting_points":
                        points_list = setting.get("value", [])
                        total_remote_pct = 0
                        for point in points_list:
                            if isinstance(point, dict):
                                total_remote_pct += int(point.get("probability_in_percent", 0))
                        return max(0, 100 - total_remote_pct)
        return 100


class GardenaDynamicSensor(CoordinatorEntity, SensorEntity):
    """Dynamic sensor for monitoring individual Gardena telemetry properties."""

    has_entity_name = False

    def __init__(self, coordinator, device_id, device_name, ability_type, prop_name, fallback_name, unit, device_class, icon, entity_category):
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
        devices = self.coordinator.data.get("devices", []) if self.coordinator.data else []
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == self._ability_type:
                        for prop in ability.get("properties", []):
                            if prop.get("name") == self._prop_name:
                                val = prop.get("value")
                                if isinstance(val, dict):
                                    val = val.get("main", str(val))
                                
                                # HARD EPOCH FILTER: Guard against empty, zero, or epoch-based timestamp fallbacks
                                if self._attr_device_class == SensorDeviceClass.TIMESTAMP:
                                    if val in [None, "0", 0, ""]:
                                        return None
                                    
                                    val_str = str(val)
                                    if "1970" in val_str or "1969" in val_str:
                                        return None
                                        
                                    try:
                                        parsed_time = dt_util.parse_datetime(val_str)
                                        if parsed_time and parsed_time.year <= 1970:
                                            return None
                                        return parsed_time
                                    except Exception:
                                        return None
                                return val
        return None

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name, "manufacturer": "Gardena (Mocker)"}

class GardenaTimeToFullChargeSensor(CoordinatorEntity, SensorEntity):
    """Calculated countdown sensor showing remaining duration until full charge / next start."""

    has_entity_name = False

    def __init__(self, coordinator, device_id, device_name, ability_type):
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
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == self._ability_type:
                        for prop in ability.get("properties", []):
                            if prop.get("name") == "timestamp_next_start":
                                val = prop.get("value")
                                if isinstance(val, dict): val = val.get("main", str(val))
                                if not val: return None
                                try:
                                    target_time = dt_util.parse_datetime(str(val))
                                    if not target_time: return None
                                    diff = target_time - dt_util.now()
                                    return max(0, int(diff.total_seconds() / 60))
                                except Exception: return None
        return None

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._device_id)}, "name": self._device_name, "manufacturer": "Gardena (Mocker)"}
