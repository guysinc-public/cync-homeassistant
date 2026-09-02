"""Constants for the Cync integration."""

DOMAIN = "cync"

CONF_TWO_FACTOR_CODE = "two_factor_code"
CONF_USER_ID = "user_id"
CONF_AUTHORIZE_STRING = "authorize_string"
CONF_EXPIRES_AT = "expires_at"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_LOGIN_RESOURCE = "login_resource"

# Refresh the access token this long before it expires. Cync tokens last seven days,
# so a full day gives the 30 second update loop thousands of retries on transient failures.
TOKEN_REFRESH_AHEAD_SECONDS = 24 * 3600
