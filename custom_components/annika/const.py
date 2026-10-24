"""Constants for the Annika integration."""

DOMAIN = "annika"

CONF_API_URL = "api_url"
CONF_UNIT_ID = "unit_id"
CONF_WEBHOOK_SECRET = "webhook_secret"

CONF_ALARM_SENSORS = "alarm_sensors"
CONF_DEVICES = "devices"
CONF_ENTITIES = "entities"
CONF_EXCLUDE = "exclude"

CONF_RAINBIRD_RECONNECT = "rainbird_reconnect"

CONF_IRRIGATION = "irrigation"
CONF_POOL_FILTER = "pool_filter"
CONF_ALARM = "alarm"
CONF_CAMERAS = "cameras"
CONF_DOORBELLS = "doorbell"
CONF_LOCKS = "locks"
CONF_HEATING = "heating"
CONF_AC = "ac"

# What a platform was loaded for: several features share the switch and sensor
# platforms, and each discovery call says which one it is setting up.
DISCOVERY_KIND = "kind"
KIND_IRRIGATION = "irrigation"
KIND_POOL_FILTER = "pool_filter"
KIND_ALARM = "alarm"
KIND_CAMERAS = "cameras"
KIND_DOORBELLS = "doorbells"
KIND_LOCKS = "locks"
KIND_HEATING = "heating"
KIND_AC = "ac"
