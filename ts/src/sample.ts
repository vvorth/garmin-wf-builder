// The readings a host frame draws at: plausible values, so a preview shows a
// face mid-life rather than at zero. Apart from the preview, so the kinds
// can read them without importing it.
import { PyFloat } from "./edit/yaml.ts";
import type { ExprValue } from "./expr.ts";

/** The sample readings, by catalogue path. */
export const SAMPLE: ReadonlyMap<string, ExprValue> = new Map<string, ExprValue>([
  ["time.clock", 0],
  ["date.today", 0],
  ["date.day_of_week", "Wed"],
  ["date.weekday", 4], // Wednesday: Gregorian.DAY_SUNDAY = 1 .. DAY_SATURDAY = 7
  ["date.day", 3],
  ["date.month", "Sep"],
  ["date.month_number", 9],
  ["date.year", 2026],
  ["time.hour", 10],
  ["time.minute", 9],
  ["time.second", 42],
  ["device.is_24_hour", true],
  // `System.UNIT_METRIC` (0) for every unit setting.
  ["device.distance_units", 0],
  ["device.elevation_units", 0],
  ["device.temperature_units", 0],
  ["device.pace_units", 0],
  ["device.do_not_disturb", false],
  ["device.notification_count", 3],
  ["device.alarm_count", 1],
  ["device.phone_connected", true],
  ["system.battery", new PyFloat(68)],
  ["system.battery_in_days", new PyFloat(9)],
  ["system.charging", false],
  ["activity.steps", 8432],
  ["activity.step_goal", 10000],
  ["activity.calories", 1840],
  ["activity.distance", 631000],
  ["activity.floors_climbed", 7],
  ["activity.floors_climbed_goal", 10],
  ["activity.move_bar_level", 2],
  ["activity.active_minutes_week", 96],
  ["activity.active_minutes_week_goal", 150],
  ["heart_rate.current", 72],
  // `Weather.CONDITION_RAIN`: a dynamic weather icon draws the glyph its box is measured with.
  ["weather.condition", 3],
  ["weather.condition_today", 3],
  ["weather.condition_tomorrow", 3],
]);

/** The wearer a gauge on a `config: slots:` slot is scaled for: illustrative, nobody's own. */
export const SAMPLE_WEARER_SEX = "male";
export const SAMPLE_WEARER_AGE = 35;
export const SAMPLE_HEART_RATE_ZONES: readonly number[] = [95, 114, 133, 152, 171, 190];

/** `ActivityMonitor.Info` goal fields, as a slot gauge's scale reads them. */
export const SAMPLE_GOALS: ReadonlyMap<string, number> = new Map([
  ["stepGoal", 10000],
  ["floorsClimbedGoal", 10],
  ["activeMinutesWeekGoal", 150],
]);

/** Illustrative raw readings for a `data` element, by complication type; 12 / "--" for one not listed. */
export const DATA_SAMPLE: ReadonlyMap<string, unknown> = new Map<string, unknown>([
  ["steps", 8432],
  ["heart_rate", 72],
  ["calories", 1840],
  ["battery", 68],
  ["body_battery", 62],
  ["floors_climbed", 7],
  ["intensity_minutes", 17],
  ["notification_count", 3],
  ["stress", 34],
  ["current_temperature", 21.4],
  ["high_low_temperature", "H 26 / L 17"],
  ["current_weather", 22],
  ["forecast_weather_1day", 1],
  ["forecast_weather_2day", 3],
  ["forecast_weather_3day", 0],
  ["sunrise", 22512],
  ["sunset", 65558],
  ["altitude", new PyFloat(511)],
  ["sea_level_pressure", new PyFloat(101675)],
  ["recovery_time", 2161],
  ["race_predictor_5k", 1480],
  ["race_predictor_10k", 3090],
  ["race_predictor_half_marathon", 6900],
  ["race_predictor_marathon", 14520],
  ["race_pace_predictor_5k", 3.38],
  ["race_pace_predictor_10k", 3.24],
  ["race_pace_predictor_half_marathon", 3.06],
  ["race_pace_predictor_marathon", 2.91],
  ["weekly_run_distance", new PyFloat(23400)],
  ["weekly_bike_distance", new PyFloat(61200)],
  ["vo2max_run", 49],
  ["vo2max_bike", 45],
  ["pulse_ox", 97],
  ["respiration_rate", 15],
  ["solar_input", 40],
  ["sleep_score", 88],
  ["calendar_events", "19:00"],
  ["date", "28 Mar"],
  ["weekday_monthday", "Wed 28"],
  ["training_status", "PRODUCTIVE"],
]);
