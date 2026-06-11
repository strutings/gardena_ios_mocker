import logging
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
# RETTET: EntityCategory må importeres fra helpers.entity i nyere HA-versjoner
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up all binary sensors automatically."""
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
                val = prop.get("value")

                # Identify binary sensors based on name or boolean type
                if prop_name in ["connection_status", "emergency_stop", "valve_open"] or isinstance(val, bool):
                    device_class = None
                    entity_category = None

                    if prop_name == "connection_status":
                        device_class = BinarySensorDeviceClass.CONNECTIVITY
                        entity_category = EntityCategory.DIAGNOSTIC
                    elif prop_name == "emergency_stop":
                        device_class = BinarySensorDeviceClass.PROBLEM
                    elif prop_name == "valve_open":
                        device_class = BinarySensorDeviceClass.OPEN

                    entities.append(
                        GardenaDynamicBinarySensor(
                            coordinator, device_id, device_name, ability_type, prop_name, device_class, entity_category
                        )
                    )

    async_add_entities(entities)


class GardenaDynamicBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Dynamic binary sensor for Gardena properties."""

    has_entity_name = True

    def __init__(self, coordinator, device_id, device_name, ability_type, prop_name, device_class, entity_category):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._ability_type = ability_type
        self._prop_name = prop_name
        
        self._attr_unique_id = f"{device_id}_{ability_type}_{prop_name}_binary"
        # RETTET: Bruker translation_key og lar navnet styres av HA sin kjerne/en.json
        self._attr_translation_key = prop_name
        self._attr_device_class = device_class
        self._attr_entity_category = entity_category

    @property
    def is_on(self) -> bool:
        """Check if the sensor is active (True / online / open)."""
        devices = self.coordinator.data.get("devices", [])
        for d in devices:
            if d.get("id") == self._device_id:
                for ability in d.get("abilities", []):
                    if ability.get("type") == self._ability_type:
                        for prop in ability.get("properties", []):
                            if prop.get("name") == self._prop_name:
                                val = prop.get("value")
                                if self._prop_name == "connection_status":
                                    return val == "online"
                                if str(val).lower() in ["true", "open", "on", "yes"]:
                                    return True
                                return bool(val) if isinstance(val, bool) else False
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Gardena (Mocker)",
        }
