"""Coordinator to handle keeping device states up to date."""

from datetime import timedelta
import logging
import time
from typing import override

from pycync import Auth, Cync, CyncDevice
from pycync.exceptions import AuthFailedError, CyncError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .auth import async_silent_login, persist_user
from .const import TOKEN_REFRESH_AHEAD_SECONDS

_LOGGER = logging.getLogger(__name__)

type CyncConfigEntry = ConfigEntry[CyncCoordinator]


class CyncCoordinator(DataUpdateCoordinator[dict[str, CyncDevice]]):
    """Coordinator to handle updating Cync device states.

    Data is keyed by the pycync device unique ID, which is also what the library's
    push updates are keyed by.
    """

    config_entry: CyncConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: CyncConfigEntry,
        cync: Cync,
        auth: Auth,
    ) -> None:
        """Initialize the Cync coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Cync Data Coordinator",
            config_entry=config_entry,
            update_interval=timedelta(seconds=30),
            always_update=True,
        )
        self.cync = cync
        self._auth = auth

    async def on_data_update(self, data: dict[str, CyncDevice]) -> None:
        """Update registered devices with new data."""
        merged_data = self.data | data if self.data else data
        self.async_set_updated_data(merged_data)

    @override
    async def _async_setup(self) -> None:
        """Persist tokens that the library refreshed while the client was being created."""
        logged_in_user = self.cync.get_logged_in_user()
        if logged_in_user.access_token != self.config_entry.data[CONF_ACCESS_TOKEN]:
            persist_user(self.hass, self.config_entry, self._auth)

    @override
    async def _async_update_data(self) -> dict[str, CyncDevice]:
        """Refresh the user's auth token when it is within a day of expiring.

        Then, fetch all current device states.
        """

        logged_in_user = self.cync.get_logged_in_user()
        if logged_in_user.expires_at - time.time() < TOKEN_REFRESH_AHEAD_SECONDS:
            await self._async_refresh_cync_credentials()

        self.cync.update_device_states()
        current_device_states = self.cync.get_devices()

        return {device.unique_id: device for device in current_device_states}

    async def _async_refresh_cync_credentials(self) -> None:
        """Refresh the Cync token, falling back to a silent re-login when Cync rejects it.

        A transport or server failure is logged and retried on the next update; the token
        is still valid for up to a day at this point. The refreshed tokens are persisted
        by the token refresh callback registered on the auth object.
        """

        try:
            await self.cync.refresh_credentials()
        except AuthFailedError as ex:
            _LOGGER.warning(
                "Cync rejected the refresh token for %s (%s), logging in again",
                self.config_entry.title,
                ex,
            )
        except CyncError as ex:
            _LOGGER.warning(
                "Could not refresh the Cync token for %s, will retry: %s",
                self.config_entry.title,
                ex,
            )
            return
        else:
            return

        # Raises ConfigEntryAuthFailed when an interactive login is needed, which the
        # coordinator turns into a re-authentication prompt.
        await async_silent_login(self._auth)
        persist_user(self.hass, self.config_entry, self._auth)

        # A new login issues a new authorize string for the TCP session, so rebuild the client.
        _LOGGER.info("Reloading the Cync integration for %s after logging in again", self.config_entry.title)
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
