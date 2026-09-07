# Cync repair: plan, open questions, and test checklist

Working notes for the Guys Inc Cync effort. The README says what the build does; this file says
what is still unknown, how to test it, and what is left to do. Dates are absolute.

## Where things are (as of 2026-09-06)

| Piece | Location |
|---|---|
| Library fork | `Guys-Inc-Public/pycync`, branch `fix/auth-and-shared-homes`, version 0.7.0 |
| Library wheel | release `v0.7.0-guysinc.1` on that fork (pinned in `manifest.json`) |
| Component | this repo, `custom_components/cync` |
| Installed copy | Home Assistant volume, `config/custom_components/cync` (identical to this repo) |
| Home Assistant | container `homeassistant`, HA 2025.11.2, host network, defined in the Plex2 docker-compose file |
| Probe script | `docs/cync_probe.py` (also staged at `config/cync_probe.py` in the volume) |

The config entry was created 2026-07-11 and has been in re-authentication since about 15 hours
after setup. It has been migrated to schema 2.2 by this build, and is waiting for the password to be
entered once. Until that happens nothing else can be verified.

## Why the stock integration failed

1. The library rotates the refresh token on every refresh, and the stock component never wrote the
   new tokens back to the entry. The next restart refreshed with a token that no longer existed.
2. A failed refresh was reported without its cause, so every failure looked like "token invalid" and
   became a two-factor prompt.
3. The library identified itself to Cync as a new app install on every login (`resource: 1`), which the
   Cync app never does.
4. Discovery only kept homes with `source == 5` from `/v2/user/{id}/subscribe/devices`. This account
   owns no home; it is invited to one. The TCP stream pushed state for 13 device IDs that discovery
   never created ("Device ID ... not found on user account").
5. The app truncates the password to 16 characters on the two-factor endpoint. The library did not, and
   Cync answers 400 to the untruncated one (Kinachi249/pycync#16).

## Open questions

These are the things the build assumes but has not proven against the live account. Each one is
answered by the test checklist below; the probe script answers them faster but needs the password
and a two-factor code in a terminal.

| # | Question | Assumption in the build | Answered by |
|---|---|---|---|
| Q1 | Does a password login that reuses the stored `resource` skip two-factor? | Yes, that is why the resource is persisted | First silent re-login (test step 5), or probe Q5 |
| Q2 | How does the shared home appear in `subscribe/devices`? Which `source`, which keys? | Any entry with a `product_id` whose property endpoint returns mesh data is a home | Devices appearing after re-auth (test step 3), or probe Q2/Q3 |
| Q3 | Does `/v2/user/token/refresh` rotate the refresh token, and is the old one single-use? | Rotates, old one is dead | Token refresh about six days after re-auth (test step 4), or probe Q4 |
| Q4 | Does opening the phone app invalidate Home Assistant's session? | No, if each has its own resource | Probe Q6, or the absence of re-auth prompts over a few weeks |
| Q5 | Does the mesh report the same device IDs the TCP stream pushes? | Yes, devices are keyed by the mesh device ID | Lights change state from the app (test step 3) |

## Test checklist

Do these in order. Before step 1, open Settings > Devices & services > Cync, open the three-dot
menu, and turn on "Enable debug logging" so the log shows the library's decisions.

1. **Re-authenticate.** Settings > Devices & services > Cync shows "Authentication expired". Enter the
   Cync email and password. Expect either the entry to load directly (Q1 answered yes without even a
   first code) or a two-factor form. If the code form appears, the email arrives within a minute;
   check spam. A rejected code most likely means a wrong password (Cync returns the same error for
   both).
2. **Confirm the entry stores the credentials.** After the flow finishes the entry title is the email
   and the log has no "no password is stored" line. Do not open `.storage/core.config_entries` to
   check; the presence of the reload without a prompt is the evidence.
3. **Confirm shared-home devices exist.** The Cync device list in Home Assistant shows the lights of the
   shared home. Toggle one from Home Assistant and from the phone app; both directions update within a
   few seconds. Log lines of the form "Device ID ... not found on user account" must be gone.
4. **Wait for the first refresh.** Cync tokens last seven days and the coordinator refreshes when less
   than a day is left, so about six days after step 1 the debug log shows the refresh and a "Stored
   refreshed Cync tokens" line. No re-auth prompt appears.
5. **Force a silent re-login.** Restart the container after step 4 or, sooner, wait for Cync to expire
   the session (it did so within a day the first time). The log shows "logging in again" followed by
   "Logged in to Cync again with the stored credentials". A re-auth prompt here means Q1 is false and
   the resource trick does not skip two-factor; note the error code from the log.
6. **Phone app coexistence.** Use the Cync app normally for a few days. Home Assistant must not ask
   for a code. If it does, note the time and compare with app use.

Anything that fails: copy the `custom_components.cync` and `pycync` log lines (they never contain
tokens) into an issue on this repo.

## Running the probe instead

The probe asks the same questions directly against the cloud API in one sitting, without touching the
Home Assistant entry. It needs the password and one two-factor code typed into a terminal.

```
docker exec -it homeassistant python3 /config/cync_probe.py
```

It writes its own tokens and resource to `config/cync_probe_state.json` (mode 600) and redacts secrets
in its output. Delete that state file when done. The probe logs in as a separate installation, which
is exactly the phone-app coexistence case, so it does not disturb the Home Assistant session.

## Cync API facts

- Base URL `https://api.gelighting.com`, corp ID `1007d2ad150c4000`.
- Access tokens last seven days (`expire_in` 604800). Refresh rotates the refresh token.
- Error bodies are `{"error": {"msg": ..., "code": ...}}`. The code is the HTTP status followed by
  four digits.

| Situation | HTTP | code | msg |
|---|---|---|---|
| Two-factor required, or wrong password on `user_auth` | 400 | 4001381 | user version error |
| Unknown user | 404 | 4041011 | |
| Bad or already-used refresh token | 400 | 4001010 | refresh token error |
| Expired access token | 403 | 4031021 | |

- The two-factor endpoint rejects passwords over 16 characters; the app truncates. The fork does too.
- The app sends a random 16-character lowercase `resource` on login and keeps it for the install.

## Gotchas

- Never read or print the tokens in `.storage/core.config_entries`. Never run the library's request
  path with the stored tokens outside Home Assistant: it auto-refreshes and rotates the refresh token
  out from under the running instance.
- Home Assistant treats a URL requirement as never installed and reinstalls the wheel on every start.
  A release asset that goes missing breaks start-up of the integration.
- The component is based on core dev plus core PR #179013 (pycync 0.6.1 bump), running on HA
  2025.11.2. Current stable is 2026.9. It loads today, but a Home Assistant upgrade should be tested
  against this override before anything else changes, and the override should be re-based on the
  version of core that ships the pycync bump.
- Issues were disabled on the pycync fork by GitHub's fork default. They are enabled now.

## Upstreaming

The maintainer of pycync asked for help in home-assistant/core#164528. Order of operations once the
checklist passes:

1. `Kinachi249/pycync`: open a PR from `fix/auth-and-shared-homes`. Split if asked: auth hardening,
   shared-home discovery, and the 16-character password fix (their #16) are separable.
2. After a pycync release that carries the changes, `home-assistant/core`: bump the requirement and
   port `auth.py`, the config flow changes, the coordinator's silent re-login, and the 2.2 entry
   migration. Core will want the password storage discussed; the alternative is a repair issue that
   asks for a code only when the resource trick fails.
3. Retire the override: delete `config/custom_components/cync` once a core release includes it.

## History

- 2026-09-01: evidence gathered from the container, plan artifact "Cync Repair Plan" published, probe
  script staged.
- 2026-09-02: pycync fork (51 tests passing on Python 3.13), component built, override installed,
  entry migrated to 2.2. Waiting on the password since then.
- 2026-09-06: these notes added to the repo. Re-authentication done in the HA UI at 21:29 EDT: Cync
  required an emailed code (the entry had no stored resource yet, so this counted as a new install).
  The entry now holds the email, password and resource. 36 lights from the shared home were created,
  no "not found on user account" lines. Q2 and Q5 answered yes. Q1, Q3 and Q4 wait on the first
  refresh (about 2026-09-12) and a restart after it.
