import logging
import time
import asyncio
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
    
    # Storage reference to cache the last successful cloud data packet
    last_successful_data: dict[str, list[Any]] = {"devices": [], "smartlets": []}
    
    async def async_get_gardena_data() -> dict[str, list[Any]]:
        """Fetch the combined data packet including devices and smartlets with transparent cache fallbacks."""
        nonlocal last_successful_data
        try:
            _LOGGER.debug("Coordinator fetching fresh device infrastructure data packet from cloud.")
            data = await gardena_manager.async_fetch_devices_and_smartlets()
            
            # SECURE CHECK: Verify that the response packet is a valid, populated dictionary mapping
            if data and isinstance(data, dict) and (data.get("devices") or data.get("smartlets")):
                # Update local cache memory core on successful transactions
                last_successful_data = data
                return data
                
            raise ValueError("Cloud gateway returned an empty or unmappable object tree.")
            
        except Exception as err:
            # SOFT FALLBACK: If the cloud drops out, timeout, or responds with 5xx, logging a warning and reuse last data frame
            if last_successful_data and last_successful_data.get("devices"):
                _LOGGER.warning(
                    "Temporary cloud communication fault intercepted: %s. Reusing cached device metrics frame to maintain stability.",
                    err
                )
                return last_successful_data
                
            raise UpdateFailed(f"Failed to update remote device infrastructure data packet and no cache available: {err}") from err

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
            _LOGGER.info("Executing service override command: start_override with duration %s min", duration)
            duration_sec = int(duration) * 60
            await gardena_manager.async_send_mower_action("manual_start", {
                "mowerTimer": duration_sec,
                "startingPointDistance": None,
                "areaId": None
            })
            
        elif service == "start_automatic":
            _LOGGER.info("Executing service command: start_automatic schedule resume")
            # FIXED: Mutate settings endpoint to clear 'schedules_paused_until' block as captured in HAR trace
            await gardena_manager.async_send_mower_setting("schedules_paused_until", "")
            
        elif service == "park_until_next_task":
            _LOGGER.info("Executing service command: park_until_next_task (park_until_next_schedule)")
            await gardena_manager.async_send_mower_action("park_until_next_schedule", {})
            
        elif service == "park_until_further_notice":
            _LOGGER.info("Executing service command: park_until_further_notice manual hold via epoch suspension")
            # FIXED: Mutate settings endpoint to push 'schedules_paused_until' into year 2040 as captured in HAR trace
            await gardena_manager.async_send_mower_setting("schedules_paused_until", "2040-12-31T22:00:00.000Z")

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
        self._schedules_setting_id = None

        # Anti-spam locks, concurrent operation fences, and payload fingerprint tracking state objects
        self._command_lock = asyncio.Lock()
        self._last_command_fingerprint = None
        self._last_command_timestamp = 0.0

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

        _LOGGER.debug("Authenticating against Husqvarna Group OAuth2 endpoint...")
        try:
            async with self.session.post(url, data=payload, headers=headers, timeout=10) as response:
                if response.status != 200:
                    resp_err = await response.text()
                    raise Exception(f"OAuth2 authentication state validation failed with code {response.status}: {resp_err}")
                data = await response.json()
                self._token = data.get("access_token")
                _LOGGER.debug("OAuth2 token provisioned successfully.")
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
                    _LOGGER.debug("Token expired on devices fetch (401). Re-authenticating...")
                    await self.async_authenticate()
                    headers["Authorization"] = f"Bearer {self._token}"
                    async with self.session.get(devices_url, headers=headers, timeout=10) as retry_resp:
                        data = await retry_resp.json()
                else:
                    data = await response.json()
                
                # SECURE CHECK: Safeguard against empty or unexpected non-dictionary payloads from network path
                if data and isinstance(data, dict):
                    devices_list = data.get("devices", [])
                
                # Locate a valid parent machine boundary ID reference and dynamically parse schedules setting ID mapping
                for device in devices_list:
                    if not isinstance(device, dict):
                        continue
                    
                    is_mower = False
                    for ability in device.get("abilities", []):
                        if isinstance(ability, dict) and ability.get("type") == "robotic_mower":
                            is_mower = True
                            self._first_device_id = device.get("id")
                            break
                    
                    if is_mower:
                        for setting in device.get("settings", []):
                            if isinstance(setting, dict) and setting.get("name") == "schedules_paused_until":
                                self._schedules_setting_id = setting.get("id")
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
                        if smartlets_data and isinstance(smartlets_data, dict):
                            smartlets_list = smartlets_data.get("data", [])
                    else:
                        _LOGGER.debug("Smartlets operational parameters query returned unhandled response status: %s", resp.status)
            except Exception as smartlet_err:
                _LOGGER.error("Background asynchronous polling thread failed capturing remote device smartlets maps data: %s", smartlet_err)

        return {
            "devices": devices_list,
            "smartlets": smartlets_list
        }

    async def async_send_mower_action(self, endpoint_command: str, payload: dict[str, Any]) -> None:
        """Transmit action dispatches directly down to the dedicated mower commands POST endpoints based on HAR log mapping."""
        current_time = time.time()
        command_fingerprint = f"action_{endpoint_command}_{str(payload)}"

        # 1. DEBOUNCE FILTER: Prevent identical repetitive transactions firing inside a tight 3.0-second safety envelope
        if command_fingerprint == self._last_command_fingerprint and (current_time - self._last_command_timestamp) < 3.0:
            _LOGGER.info("Anti-spam execution guard activated: Suppressed duplicate mower action payload targeting '%s' to block gateway 429 rate-limits.", endpoint_command)
            return

        # 2. CONCURRENT TRANSACTION LOCK FENCE: Block overlapping requests while server pipelines are still processing an active operation
        if self._command_lock.locked() and command_fingerprint == self._last_command_fingerprint:
            _LOGGER.debug("Suppressed concurrent request delivery frame for action execution '%s' - previous remote server network frame transaction is still processing.", endpoint_command)
            return

        async with self._command_lock:
            _LOGGER.debug("Acquired command lock for firing action '%s'.", endpoint_command)
            self._last_command_fingerprint = command_fingerprint
            self._last_command_timestamp = current_time

            try:
                if not self._token:
                    await self.async_authenticate()
                    
                if not self._first_device_id:
                    await self.async_fetch_devices_and_smartlets()

                location_id = self.entry.data[CONF_LOCATION_ID]
                url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._first_device_id}/abilities/mower/commands/{endpoint_command}?locationId={location_id}"

                headers = {
                    "Authorization": f"Bearer {self._token}",
                    "Authorization-Provider": "husqvarna",
                    "X-Api-Key": CLIENT_ID,
                    "X-Key": CLIENT_ID,
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"
                }

                async with self.session.post(url, json=payload, headers=headers, timeout=10) as response:
                    if response.status == 401:
                        _LOGGER.debug("Token expired during action execution (401). Retrying with fresh token...")
                        await self.async_authenticate()
                        headers["Authorization"] = f"Bearer {self._token}"
                        async with self.session.post(url, json=payload, headers=headers, timeout=10) as retry_resp:
                            pass
                    elif response.status == 429:
                        _LOGGER.warning("Mower action command '%s' was rate limited by the gateway (Status 429).", endpoint_command)
                    elif response.status not in [200, 202, 204]:
                        resp_txt = await response.text()
                        _LOGGER.error("Mower action '%s' rejected by cloud with status %s: %s", endpoint_command, response.status, resp_txt)
            except Exception as err:
                _LOGGER.error("Fatal exception inside action execution lock for '%s': %s", endpoint_command, err)
                # Reset timestamp on error to allow an immediate retry
                self._last_command_timestamp = 0.0

    async def async_send_mower_setting(self, setting_name: str, value: str) -> None:
        """Mutate specific device schedule settings states directly via the verified PUT endpoints mapped from the trace telemetry."""
        current_time = time.time()
        setting_fingerprint = f"setting_{setting_name}_{str(value)}"

        # 1. DEBOUNCE FILTER: Prevent identical repetitive transactions firing inside a tight 3.0-second safety envelope
        if setting_fingerprint == self._last_command_fingerprint and (current_time - self._last_command_timestamp) < 3.0:
            _LOGGER.info("Anti-spam execution guard activated: Suppressed duplicate mower setting alteration targeting '%s' to block gateway 429 rate-limits.", setting_name)
            return

        # 2. CONCURRENT TRANSACTION LOCK FENCE: Block overlapping requests while server pipelines are still processing an active operation
        if self._command_lock.locked() and setting_fingerprint == self._last_command_fingerprint:
            _LOGGER.debug("Suppressed concurrent request delivery frame for setting alteration '%s' - previous remote server network frame transaction is still processing.", setting_name)
            return

        async with self._command_lock:
            _LOGGER.debug("Acquired command lock for mutating setting '%s'.", setting_name)
            self._last_command_fingerprint = setting_fingerprint
            self._last_command_timestamp = current_time

            try:
                if not self._token:
                    await self.async_authenticate()
                    
                if not self._first_device_id or not self._schedules_setting_id:
                    await self.async_fetch_devices_and_smartlets()

                if not self._schedules_setting_id:
                    _LOGGER.error("Cannot alter mower setting '%s' because target settings GUID payload mapping was not populated.", setting_name)
                    return

                location_id = self.entry.data[CONF_LOCATION_ID]
                url = f"https://bff-api.sg.dss.husqvarnagroup.net/v1/devices/{self._first_device_id}/settings/{self._schedules_setting_id}?locationId={location_id}"

                payload = {
                    "settings": {
                        "name": setting_name,
                        "value": value,
                        "device": self._first_device_id
                    }
                }

                headers = {
                    "Authorization": f"Bearer {self._token}",
                    "Authorization-Provider": "husqvarna",
                    "X-Api-Key": CLIENT_ID,
                    "X-Key": CLIENT_ID,
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"
                }

                async with self.session.put(url, json=payload, headers=headers, timeout=10) as response:
                    if response.status == 401:
                        _LOGGER.debug("Token expired during setting mutation (401). Retrying with fresh token...")
                        await self.async_authenticate()
                        headers["Authorization"] = f"Bearer {self._token}"
                        async with self.session.put(url, json=payload, headers=headers, timeout=10) as retry_resp:
                            pass
                    elif response.status == 429:
                        _LOGGER.warning("Mower settings shift '%s' was rate limited by the server gateway (Status 429).", setting_name)
                    elif response.status not in [200, 202, 204]:
                        resp_txt = await response.text()
                        _LOGGER.error("Mower setting mutation '%s' rejected by server with status %s: %s", setting_name, response.status, resp_txt)
            except Exception as err:
                _LOGGER.error("Fatal exception inside setting mutation lock for '%s': %s", setting_name, err)
                self._last_command_timestamp = 0.0
