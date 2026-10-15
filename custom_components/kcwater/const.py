"""Constants for KC Water."""

from datetime import timedelta

DOMAIN = "kcwater"
CONF_ACCOUNT = "account"
CONF_CUSTOMER_ID = "customer_id"
CONF_SERVICE_ID = "service_id"
CONF_ACCOUNT_NUMBER = "account_number"
API_BASE = "https://my.kcwater.us/rest"
TOKEN_PATH = "/oauth/token"
USAGE_PATH = "/usage/month/day"
UPDATE_INTERVAL = timedelta(hours=6)

# These values are the ones present in the supplied starter. Their validity must
# be confirmed against a sanitized capture before a live deployment is claimed.
OAUTH_CLIENT_ID = "webClientIdPassword"
OAUTH_CLIENT_SECRET = "secret"
