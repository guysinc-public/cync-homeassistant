"""Config flow for the Cync integration."""

from collections.abc import Mapping
import logging
from typing import Any, override

from pycync import Auth
from pycync.exceptions import AuthFailedError, CyncError, TwoFactorRequiredError
import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AUTHORIZE_STRING,
    CONF_EXPIRES_AT,
    CONF_LOGIN_RESOURCE,
    CONF_REFRESH_TOKEN,
    CONF_TWO_FACTOR_CODE,
    CONF_USER_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_TWO_FACTOR_SCHEMA = vol.Schema({vol.Required(CONF_TWO_FACTOR_CODE): str})


class CyncConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cync."""

    VERSION = 2
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        self._auth: Auth | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Attempt login with user credentials."""
        errors: dict[str, str] = {}

        if user_input:
            self._start_login(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
            errors, two_factor_needed = await self._async_login()
            if two_factor_needed:
                return await self.async_step_two_factor()
            if not errors:
                return await self._create_config_entry()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_two_factor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Attempt login with the two factor auth code sent to the user."""
        errors: dict[str, str] = {}

        if user_input:
            errors, two_factor_needed = await self._async_login(
                user_input[CONF_TWO_FACTOR_CODE]
            )
            if not errors and not two_factor_needed:
                return await self._create_config_entry()
            if two_factor_needed:
                errors = {"base": "invalid_auth"}

        return self.async_show_form(
            step_id="two_factor",
            data_schema=STEP_TWO_FACTOR_SCHEMA,
            errors=errors,
            description_placeholders={CONF_EMAIL: self._auth.username if self._auth else ""},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user that reauth is required and prompt for Cync credentials."""
        errors: dict[str, str] = {}

        reauth_entry = self._get_reauth_entry()

        if user_input:
            # Keep the login resource the entry already has, so Cync sees the same
            # installation logging in again rather than a new one.
            self._start_login(
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                reauth_entry.data.get(CONF_LOGIN_RESOURCE),
            )
            errors, two_factor_needed = await self._async_login()
            if two_factor_needed:
                return await self.async_step_two_factor()
            if not errors:
                return await self._create_config_entry()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {CONF_EMAIL: reauth_entry.data.get(CONF_EMAIL, reauth_entry.title)},
            ),
            errors=errors,
            description_placeholders={CONF_EMAIL: reauth_entry.title},
        )

    def _start_login(
        self, email: str, password: str, resource: str | None = None
    ) -> None:
        """Start a fresh login attempt with the submitted credentials."""
        self._auth = Auth(
            async_get_clientsession(self.hass),
            username=email,
            password=password,
            resource=resource,
        )

    async def _async_login(
        self, two_factor_code: str | None = None
    ) -> tuple[dict[str, str], bool]:
        """Attempt to log in and return (errors, two_factor_needed)."""
        assert self._auth is not None

        try:
            await self._auth.login(two_factor_code)
        except TwoFactorRequiredError:
            return {}, True
        except AuthFailedError as ex:
            _LOGGER.debug("Cync login failed: %s (code %s)", ex, ex.code)
            return {"base": "invalid_auth"}, False
        except CyncError as ex:
            _LOGGER.debug("Cync login could not be completed: %s", ex)
            return {"base": "cannot_connect"}, False
        except Exception:
            _LOGGER.exception("Unexpected exception")
            return {"base": "unknown"}, False

        return {}, False

    async def _create_config_entry(self) -> ConfigFlowResult:
        """Create the Cync config entry using input user data."""
        assert self._auth is not None

        cync_user = self._auth.user
        user_email = self._auth.username
        await self.async_set_unique_id(str(cync_user.user_id))

        config_data = {
            CONF_USER_ID: cync_user.user_id,
            CONF_AUTHORIZE_STRING: cync_user.authorize,
            CONF_EXPIRES_AT: cync_user.expires_at,
            CONF_ACCESS_TOKEN: cync_user.access_token,
            CONF_REFRESH_TOKEN: cync_user.refresh_token,
            CONF_EMAIL: user_email,
            CONF_PASSWORD: self._auth.password,
            CONF_LOGIN_RESOURCE: self._auth.resource,
        }

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                entry=self._get_reauth_entry(),
                title=user_email,
                data_updates=config_data,
            )

        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=user_email, data=config_data)
