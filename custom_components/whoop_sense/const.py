"""Constants for WHOOP Sense."""

from datetime import timedelta

DOMAIN = "whoop_sense"

UPDATE_INTERVAL = timedelta(minutes=15)
RECOMPUTE_INTERVAL = timedelta(minutes=5)
BODY_INTERVAL = timedelta(hours=6)

CONF_WAKE_WEEKDAY = "wake_weekday"
CONF_WAKE_WEEKEND = "wake_weekend"
CONF_WAKE_ENTITY = "wake_entity"
DEFAULT_WAKE_WEEKDAY = "06:30:00"
DEFAULT_WAKE_WEEKEND = "09:00:00"
