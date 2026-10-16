<img src="docs/assets/readme-header.svg" alt="Guys Inc" width="100%">

# cync-homeassistant

A drop-in replacement for Home Assistant's built-in Cync integration: sign-in that survives token rotation, and discovery of shared homes.

![Licence](https://img.shields.io/badge/licence-MIT-ff67bd?style=flat-square&labelColor=0e090f)
![Build](https://github.com/guysinc-public/cync-homeassistant/actions/workflows/check.yml/badge.svg)
![Docs](https://img.shields.io/badge/docs-reviewed_2026--10--15-22dcb3?style=flat-square&labelColor=0e090f)

It replaces the stock `cync` integration to fix two problems:

1. **Two-factor codes every few days.** The stock integration never persisted the refresh tokens the
   library rotated, threw away the reason a refresh failed, mistook a wrong password for a two-factor
   challenge, and identified itself to Cync as a new app install on every login. This build sends a stable
   login "resource", stores every token rotation, retries transient refresh failures instead of asking for
   a code, and logs in again with the stored password when Cync does expire the session. A two-factor code
   is only requested when Cync insists on one.
2. **Homes shared with your account showed no devices.** Discovery only looked at homes the account owns.
   This build discovers shared homes as well, and creates their devices even when your account has no
   record of them.

It runs on the [Guys Inc fork of pycync](https://github.com/guysinc-forks/pycync), branch
`fix/auth-and-shared-homes`, installed from the wheel attached to that fork's release.

## Install

Copy `custom_components/cync` into your Home Assistant `config/custom_components/` directory and restart
Home Assistant. A custom integration with the same domain replaces the built-in one; delete the directory
to go back. Home Assistant installs the pinned pycync wheel from GitHub on start-up.

Existing entries are migrated in place. The first re-authentication after installing stores your email and
password on the entry so that later expiries are handled without you.

## Status

Tested against Home Assistant 2025.11 on a container install. The changes are intended for upstream:
the library changes go to `Kinachi249/pycync`, the component changes to `home-assistant/core`.
