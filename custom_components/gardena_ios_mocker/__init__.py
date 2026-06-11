import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_LOCATION_ID, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "lawn_mower", "number", "switch", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gardena iOS Mocker integration instance from a ConfigEntry."""
    gardena_manager = GardenaApiManager(hass, entry)
    
    async def async_get_gardena_data() -> dict[str, list[Any]]:
        """Fetch the combined data packet including devices and smartlets."""
        try:
            return await gardena_manager.async_fetch_devices_and_smartlets()
        except Exception as err:
            raise UpdateFailed(f"Failed to update remote device infrastructure data packet: {err}") from err

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

    # --- CENTRALLY MANAGED CORE SYSTEM SERVICES ---
    async def handle_mower_service(call: ServiceCall) -> None:
        """Handle execution workflows triggered by centralized custom mower services."""
        service = call.service
        
        if service == "start_override":
            duration = call.data.get("duration", 180)
            # FIXED: Changed string logging interpolation to use 'duration' instead of non-existent 'target_state'
            _LOGGER.info("Executing service override command: start_override with duration %s min", duration)
            await gardena_manager.async_send_raw_command("START", {"duration": int(duration)})
            
        elif service == "start_automatic":
            _LOGGER.info("Executing service command: start_automatic schedule resume")
            await gardena_manager.async_send_raw_command("START_RESUME_SCHEDULE")
            
        elif service == "park_until_next_task":
            _LOGGER.info("Executing service command: park_until_next_task")
            await gardena_manager.async_send_raw_command("PARK_UNTIL_NEXT_TASK")
            
        elif service == "park_until_further_notice":
            _LOGGER.info("Executing service command: park_until_further_notice manual hold")
            await gardena_manager.async_send_raw_command("PARK_UNTIL_FURTHER_NOTICE")

        # Force an immediate data refresh cycle after transmitting runtime commands
        hass.async_create_task(coordinator.async_request_refresh())

    # FIXED: Added schema verification definitions for the override duration parameters block
    hass.services.async_register(
        DOMAIN, 
        "start_override", 
        handle_mower_service,
        schema=vol.Schema({
            vol.Optional("duration", default=180): cv.positive_int
        }),
        supports_response=False
    )
    
    hass.services.async_register(DOMAIN, "start_automatic", handle_mower_service)
    hass.services.async_register(DOMAIN, "park_until_next_task", handle_mower_service)
    hass.services.async_register(DOMAIN, "park_until_further_notice", handle_mower_service)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload integration platform entities and tear down custom system services handles."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.services.async_remove(DOMAIN, "start_override")
        hass.services.async_remove(DOMAIN, "start_automatic")
        hass.services.async_remove(DOMAIN, "park_until_next_task")
        hass.services.async_remove(DOMAIN, "park_until_further_notice")
    return unload_ok


class GardenaApiManager:
    """Manages secure access token provisioning and direct transactional cloud endpoint operations."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize HTTP client session controllers and device orientation handles."""
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self._token = None
        self._first_device_id = None

    async def async_authenticate(self) -> str:
        """Provision a secure bearer access token against the OAuth2 security identity management service."""
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
                    raise Exception(f"OAuth2 authentication state validation failed with code {response.status}: {resp_err}")
                data = await response.json()
                self._token = data.get("access_token")
                return self._token
        except Exception as err:
            _LOGGER.error("Fatal network exception intercepted during credentials token provision: %s", err)
            raise

    async def async_fetch_devices_and_smartlets(self) -> dict[str, list[Any]]:
        """Query primary device definitions arrays and contextual cloud smartlet metrics sequentially."""
        location_id = self.entry.data[CONF_LOCATION_ID]
        devices_url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices?locationId={location_id}"

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

        devices_list = []
        smartlets_list = []

        # 1. Retrieve Core Physical Infrastructure Component Arrays
        try:
            async with self.session.get(devices_url, headers=headers, timeout=10) as response:
                if response.status == 401:
                    await self.async_authenticate()
                    headers["Authorization"] = f"Bearer {self._token}"
                    async with self.session.get(devices_url, headers=headers, timeout=10) as retry_resp:
                        data = await retry_resp.json()
                else:
                    data = await response.json()
                
                devices_list = data.get("devices", [])
                
                # Locate a valid parent machine boundary ID reference for nested relational lookups
                for device in devices_list:
                    if not isinstance(device, dict):
                        continue
                    for ability in device.get("abilities", []):
                        if isinstance(ability, dict) and ability.get("type") == "robotic_mower":
                            self._first_device_id = device.get("id")
                            break
        except Exception as err:
            _LOGGER.error("Fatal network exception generated fetching remote device infrastructure tree: %s", err)
            raise

        # 2. Retrieve Cloud Smartlets Runtime and State Constraints Metrics
        if self._first_device_id:
            smartlets_url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/locations/{location_id}/smartlets?device_id={self._first_device_id}"
            try:
                async with self.session.get(smartlets_url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        smartlets_data = await resp.json()
                        smartlets_list = smartlets_data.get("data", [])
                    else:
                        _LOGGER.debug("Smartlets operational parameters query returned unhandled response status: %s", resp.status)
            except Exception as smartlet_err:
                _LOGGER.error("Background asynchronous polling thread failed capturing remote device smartlets maps data: %s", smartlet_err)

        return {
            "devices": devices_list,
            "smartlets": smartlets_list
        }

    async def async_send_raw_command(self, command_id: str, parameters: dict[str, Any] = None) -> None:
        """Transmit structured runtime execution instructions maps down onto the central hardware gateway tree."""
        if not self._token:
            await self.async_authenticate()
            
        if not self._first_device_id:
            await self.async_fetch_devices_and_smartlets()

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
                    # FIXED: Added missing live header injection mapping upon token refresh cycle retry executions
                    headers["Authorization"] = f"Bearer {self._token}"
                    await self.session.post(url, json=payload, headers=headers, timeout=10)
                elif response.status not in [200, 202]:
                    resp_txt = await response.text()
                    _LOGGER.error("Command transaction %s rejected by infrastructure service node with status %s: %s", command_id, response.status, resp_txt)
        except Exception as err:
            _LOGGER.error("Network communication timeout exception intercepted while posting runtime directive parameters maps: %s", err)
