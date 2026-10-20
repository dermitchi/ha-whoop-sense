"""Sensors for WHOOP Sense."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WhoopConfigEntry, WhoopCoordinator
from .logic import ZONE_GREEN, ZONE_RED, ZONE_YELLOW

BPM = "bpm"
MEAS = SensorStateClass.MEASUREMENT


@dataclass(frozen=True, kw_only=True)
class WhoopSensorDescription(SensorEntityDescription):
    """`key` is also the key in WhoopData.values / .attrs."""


def _pct(key: str, **kw: Any) -> WhoopSensorDescription:
    return WhoopSensorDescription(
        key=key, translation_key=key, native_unit_of_measurement=PERCENTAGE, state_class=MEAS, **kw
    )


def _hours(key: str, **kw: Any) -> WhoopSensorDescription:
    return WhoopSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        state_class=MEAS,
        **kw,
    )


def _ts(key: str, **kw: Any) -> WhoopSensorDescription:
    return WhoopSensorDescription(
        key=key, translation_key=key, device_class=SensorDeviceClass.TIMESTAMP, **kw
    )


def _plain(key: str, unit: str | None = None, **kw: Any) -> WhoopSensorDescription:
    return WhoopSensorDescription(
        key=key, translation_key=key, native_unit_of_measurement=unit, state_class=MEAS, **kw
    )


def _kcal(key: str) -> WhoopSensorDescription:
    return WhoopSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_CALORIE,
        suggested_display_precision=0,
        state_class=MEAS,
    )


SENSORS: tuple[WhoopSensorDescription, ...] = (
    # Recovery
    _pct("recovery"),
    WhoopSensorDescription(
        key="recovery_zone",
        translation_key="recovery_zone",
        device_class=SensorDeviceClass.ENUM,
        options=[ZONE_GREEN, ZONE_YELLOW, ZONE_RED],
    ),
    _plain("resting_heart_rate", BPM),
    _plain("hrv", UnitOfTime.MILLISECONDS, suggested_display_precision=0),
    _pct("spo2", suggested_display_precision=1),
    WhoopSensorDescription(
        key="skin_temperature",
        translation_key="skin_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        state_class=MEAS,
    ),
    # Sleep
    _pct("sleep_performance"),
    _pct("sleep_consistency"),
    _pct("sleep_efficiency", suggested_display_precision=0),
    _plain("respiratory_rate", "1/min", suggested_display_precision=1),
    _hours("sleep_duration"),
    _hours("time_in_bed"),
    _hours("deep_sleep"),
    _hours("rem_sleep"),
    _hours("light_sleep"),
    _hours("awake_time"),
    _plain("sleep_cycles"),
    _plain("disturbances"),
    _ts("sleep_start"),
    _ts("sleep_end"),
    _hours("sleep_need_last"),
    _hours("sleep_need_tonight"),
    _ts("bedtime"),
    # Day
    _plain("strain", suggested_display_precision=1),
    _kcal("calories"),
    _plain("average_heart_rate", BPM),
    _plain("max_heart_rate_today", BPM),
    # Workouts
    WhoopSensorDescription(key="last_workout", translation_key="last_workout"),
    _plain("last_workout_strain", suggested_display_precision=1),
    _kcal("last_workout_calories"),
    WhoopSensorDescription(
        key="last_workout_duration",
        translation_key="last_workout_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=MEAS,
    ),
    _plain("workouts_today"),
    # Body
    WhoopSensorDescription(
        key="weight",
        translation_key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        state_class=MEAS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _plain("max_heart_rate", BPM, entity_category=EntityCategory.DIAGNOSTIC),
    WhoopSensorDescription(
        key="height",
        translation_key="height",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhoopConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(WhoopSensor(coordinator, desc) for desc in SENSORS)


class WhoopSensor(CoordinatorEntity[WhoopCoordinator], SensorEntity):
    """One value out of the computed WHOOP summary."""

    _attr_has_entity_name = True
    entity_description: WhoopSensorDescription

    def __init__(self, coordinator: WhoopCoordinator, desc: WhoopSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{desc.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="WHOOP",
            model="WHOOP API v2",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.values.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.coordinator.data.attrs.get(self.entity_description.key)
