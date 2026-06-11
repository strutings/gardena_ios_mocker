import logging
import aiohttp
import voluptuous as vol
import base64
import json
import traceback

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CLIENT_ID

_LOGGER = logging.getLogger(__name__)

def decode_user_id_from_jwt(token: str) -> str | None:
    """Decode the JWT token locally in memory to extract the unique user ID."""
    try:
        if not token or "." not in token:
            return None
        payload_segment = token.split(".")[1]
        rem = len(payload_segment) % 4
        if rem > 0:
            payload_segment += "=" * (4 - rem)
            
        decoded_bytes = base64.b64decode(payload_segment)
        payload_data = json.loads(decoded_bytes.decode("utf-8"))
        
        user_id = payload_data.get("user_id") or payload_data.get("sub")
        return str(user_id) if user_id else None
    except Exception as err:
        _LOGGER.error("Failed to extract user ID from token payload: %s", err)
        return None

async def async_get_location_id(username: str, password: str) -> str | None:
    """Fetch the location ID dynamically by parsing the BFF response."""
    access_token = None  # FIXED: Initialized here to prevent UnboundLocalError on login failures
    
    auth_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Accept-Language": "en-US;q=1.0, en;q=0.9",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    }

    async with aiohttp.ClientSession() as session:
        token_url = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
        
        payload = {
            "grant_type": "password",
            "client_id": "smartgarden-jwt-client",
            "client_secret": "",
            "username": username,
            "password": password
        }
        
        try:
            _LOGGER.info("Authenticating user against Gardena Auth...")
            async with session.post(token_url, data=payload, headers=auth_headers, timeout=10) as response:
                if response.status != 200:
                    resp_err = await response.text()
                    _LOGGER.error("Authentication login failed with status %s: %s", response.status, resp_err)
                    return None
                    
                token_data = await response.json()
                access_token = token_data.get("access_token")
                
            if not access_token:
                _LOGGER.error("Received response from Auth, but access_token was missing.")
                return None

            user_id = decode_user_id_from_jwt(access_token)
            if not user_id:
                _LOGGER.error("Failed to find a valid user_id in the token.")
                return None

            data_headers = {
                "Authorization": f"Bearer {access_token}",
                "Authorization-Provider": "husqvarna",
                "X-Api-Key": str(CLIENT_ID),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"
            }

            url = "https://bff-api.sg.dss.husqvarnagroup.net/v1/locations"
            query_params = {
                "locationId": "null",
                "user_id": str(user_id)
            }
            
            _LOGGER.info("Dynamically fetching location list from BFF for user_id: %s", user_id)
            async with session.get(url, headers=data_headers, params=query_params, timeout=10) as response:
                resp_text = await response.text()
                
                if response.status == 200:
                    raw_data = json.loads(resp_text)
                    locations_list = []
                    
                    if isinstance(raw_data, list):
                        locations_list = raw_data
                    elif isinstance(raw_data, dict):
                        locations_list = raw_data.get("locations", raw_data.get("data", []))
                    
                    if locations_list and len(locations_list) > 0:
                        location_id = locations_list[0].get("id") or locations_list[0].get("locationId")
                        _LOGGER.info("Success! Dynamically found location ID: %s", location_id)
                        return str(location_id)
                    else:
                        _LOGGER.error("Response received, but found no location ID in the JSON structure: %s", resp_text)
                        return None
                else:
                    _LOGGER.error("BFF lookup failed. Status %s: %s", response.status, resp_text)
                    return None

        except Exception as err:
            _LOGGER.error("Critical error in async_get_location_id: %s\n%s", err, traceback.format_exc())
            return None


class GardenaIosMockerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for Gardena iOS Mocker."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """First step when the user adds the integration manually."""
        errors = {}

        if user_input is not None:
            username = user_input["username"]
            password = user_input["password"]

            location_id = await async_get_location_id(username, password)

            if location_id:
                return self.async_create_entry(
                    title=f"Gardena ({username})",
                    data={
                        "username": username,
                        "password": password,
                        "location_id": location_id,
                    },
                )
            else:
                errors["base"] = "cannot_connect"

        DATA_SCHEMA = vol.Schema(
            {
                vol.Required("username"): cv.string,
                vol.Required("password"): cv.string,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
