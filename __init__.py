import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_LOCATION_ID, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "lawn_mower", "number", "switch"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gardena iOS Mocker from a ConfigEntry."""
    gardena_manager = GardenaApiManager(hass, entry)
    
    async def async_get_gardena_data():
        try:
            return await gardena_manager.async_fetch_devices()
        except Exception as err:
            raise UpdateFailed(f"Failed to update device data: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Gardena iOS Devices",
        update_method=async_get_gardena_data,
        update_interval=timedelta(seconds=60),
    )

    coordinator.api_manager = gardena_manager
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- SYSTEM SERVICES HANDLING ---
    async def handle_mower_service(call: ServiceCall):
        """Handle custom mower services centrally."""
        service = call.service
        
        if service == "start_override":
            duration = call.data.get("duration", 180)
            _LOGGER.info("Running service: start_override with duration %s min", duration)
            await gardena_manager.async_send_raw_command("START", {"duration": int(duration)})
            
        elif service == "start_automatic":
            _LOGGER.info("Running service: start_automatic")
            await gardena_manager.async_send_raw_command("START_RESUME_SCHEDULE")
            
        elif service == "park_until_next_task":
            _LOGGER.info("Running service: park_until_next_task")
            await gardena_manager.async_send_raw_command("PARK_UNTIL_NEXT_TASK")
            
        elif service == "park_until_further_notice":
            _LOGGER.info("Running service: park_until_further_notice")
            await gardena_manager.async_send_raw_command("PARK_UNTIL_FURTHER_NOTICE")

        # Force an immediate data refresh after the command has been sent
        hass.async_create_task(coordinator.async_request_refresh())

    # FIXED: Register service descriptions directly in the Python code to bypass broken services.yaml loading
    hass.services.async_register(
        DOMAIN, 
        "start_override", 
        handle_mower_service,
        supports_response=False
    )
    
    hass.services.async_register(DOMAIN, "start_automatic", handle_mower_service)
    hass.services.async_register(DOMAIN, "park_until_next_task", handle_mower_service)
    hass.services.async_register(DOMAIN, "park_until_further_notice", handle_mower_service)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove an integration instance (ConfigEntry) and unregister services."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.services.async_remove(DOMAIN, "start_override")
        hass.services.async_remove(DOMAIN, "start_automatic")
        hass.services.async_remove(DOMAIN, "park_until_next_task")
        hass.services.async_remove(DOMAIN, "park_until_further_notice")
    return unload_ok


class GardenaApiManager:
    """Handles authentication against OAuth2 and device API calls."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self._token = None
        self._first_device_id = None

    async def async_authenticate(self) -> str:
        """Log in using a form-url-encoded payload against the universal iOS client configuration."""
        url = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
        payload = {
            "grant_type": "password",
            "client_id": "smartgarden-jwt-client",
            "client_secret": "",
            "username": self.entry.data[CONF_USERNAME],
            "password": self.entry.data[CONF_PASSWORD]
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Accept-Language": "en-US;q=1.0, en-NO;q=0.9",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Cargo 5.0.1"
        }

        try:
            async with self.session.post(url, data=payload, headers=headers, timeout=10) as response:
                if response.status != 200:
                    resp_err = await response.text()
                    raise Exception(f"OAuth2 login failed with status: {response.status}. Details: {resp_err}")
                data = await response.json()
                self._token = data.get("access_token")
                return self._token
        except Exception as err:
            _LOGGER.error("Failed to authenticate Gardena user: %s", err)
            raise

    async def async_fetch_devices(self) -> dict:
        """Fetch the device list from the BFF API and cache the device reference."""
        location_id = self.entry.data[CONF_LOCATION_ID]
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices?locationId={location_id}"

        if not self._token:
            await self.async_authenticate()

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"
        }

        try:
            async with self.session.get(url, headers=headers, timeout=10) as response:
                if response.status == 401:
                    await self.async_authenticate()
                    return await self.async_fetch_devices()
                
                data = await response.json()
                
                # Identify the mower to cache the correct deviceId for system services
                devices = data.get("devices", [])
                for device in devices:
                    for ability in device.get("abilities", []):
                        if ability.get("type") == "robotic_mower":
                            self._first_device_id = device.get("id")
                            break
                return data
        except Exception as err:
            _LOGGER.error("Error fetching device list: %s", err)
            raise

    async def async_send_raw_command(self, command_id: str, parameters: dict = None) -> None:
        """Helper function to send control commands directly to the gateway."""
        if not self._token:
            await self.async_authenticate()
            
        if not self._first_device_id:
            await self.async_fetch_devices()

        location_id = self.entry.data[CONF_LOCATION_ID]
        url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/commands?locationId={location_id}"
        
        payload = {
            "id": command_id,
            "abilityId": "robotic_mower",
            "deviceId": self._first_device_id
        }
        if parameters:
            payload["parameters"] = parameters

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Authorization-Provider": "husqvarna",
            "X-Api-Key": CLIENT_ID,
            "X-Key": CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"
        }

        try:
            async with self.session.post(url, json=payload, headers=headers, timeout=10) as response:
                if response.status == 401:
                    await self.async_authenticate()
                    headers["Authorization"] = f"Bearer {self._token}"
                    await self.session.post(url, json=payload, headers=headers, timeout=10)
                elif response.status not in [200, 202]:
                    resp_txt = await response.text()
                    _LOGGER.error("Direct command %s failed with status %s: %s", command_id, response.status, resp_txt)
        except Exception as err:
            _LOGGER.error("Network error during direct command: %s", err)
