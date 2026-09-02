"""Session helpers for the Cync integration: building the client auth, persisting tokens, silent re-login."""

import logging

from pycync import Auth, User
from pycync.exceptions import AuthFailedError, CyncError, TwoFactorRequiredError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AUTHORIZE_STRING,
    CONF_EXPIRES_AT,
    CONF_LOGIN_RESOURCE,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
)

_LOGGER = logging.getLogger(__name__)


def build_auth(hass: HomeAssistant, entry: ConfigEntry) -> Auth:
    """Build a pycync Auth from the stored tokens, credentials and login resource of a config entry.

    The token refresh callback is registered here as well, so that every token rotation
    the library performs on its own is written back to the entry immediately.
    """
    user_info = User(
        entry.data[CONF_ACCESS_TOKEN],
        entry.data[CONF_REFRESH_TOKEN],
        entry.data[CONF_AUTHORIZE_STRING],
        entry.data[CONF_USER_ID],
        expires_at=entry.data[CONF_EXPIRES_AT],
    )
    auth = Auth(
        async_get_clientsession(hass),
        user=user_info,
        username=entry.data.get(CONF_EMAIL),
        password=entry.data.get(CONF_PASSWORD),
        resource=entry.data.get(CONF_LOGIN_RESOURCE),
    )
    auth.set_token_refresh_callback(lambda user: persist_user(hass, entry, auth))
    return auth


@callback
def persist_user(hass: HomeAssistant, entry: ConfigEntry, auth: Auth) -> None:
    """Write the auth's current tokens and login resource to the config entry."""
    user = auth.user
    new_data = {
        **entry.data,
        CONF_ACCESS_TOKEN: user.access_token,
        CONF_REFRESH_TOKEN: user.refresh_token,
        CONF_EXPIRES_AT: user.expires_at,
        CONF_AUTHORIZE_STRING: user.authorize,
        CONF_USER_ID: user.user_id,
        CONF_LOGIN_RESOURCE: auth.resource,
    }
    if new_data != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.debug("Stored refreshed Cync tokens for %s", entry.title)


async def async_silent_login(auth: Auth) -> User:
    """Log in again with the stored password, without asking anyone for a two-factor code.

    Raises ConfigEntryAuthFailed when a new interactive login is needed, and
    ConfigEntryNotReady when Cync could not be reached.
    """
    if not auth.username or not auth.password:
        raise ConfigEntryAuthFailed(
            "Cync rejected the stored token and no password is stored, please re-authenticate"
        )

    try:
        user = await auth.login(request_code=False)
    except TwoFactorRequiredError as ex:
        raise ConfigEntryAuthFailed(
            "Cync requires a new two-factor code, please re-authenticate"
        ) from ex
    except AuthFailedError as ex:
        raise ConfigEntryAuthFailed(
            f"Cync rejected the stored credentials ({ex.msg or ex}), please re-authenticate"
        ) from ex
    except CyncError as ex:
        raise ConfigEntryNotReady(f"Unable to log in to Cync: {ex}") from ex

    _LOGGER.info("Logged in to Cync again with the stored credentials for %s", auth.username)
    return user
