// The `series:` a `graph` element may plot, and how each is read on the
// device, and why a quantity it cannot plot is unavailable.
//
// Every field name and "or Null" was checked against the SDK's own docs
// (`Toybox/ActivityMonitor.html`, `.../ActivityMonitor/History.html`,
// `.../ActivityMonitor/ActiveMinutes.html`, `Toybox/Weather/HourlyForecast.html`,
// `Toybox/Weather/DailyForecast.html`).

import { Catalogue } from "./diagnostics.ts";

/** How a series' samples are obtained on the device. */
export type Acquisition = "heart_rate" | "activity_history" | "hourly_forecast" | "daily_forecast";

export interface AcquisitionInfo {
  /** The Toybox module the call needs. */
  module: string;
  /** The Monkey C expression that acquires the array; unused for `heart_rate`. */
  call: string;
  /** Whether the array is newest-first, so the generated loop reads it back to front. */
  newestFirst: boolean;
  /** Whether the call itself can return null. */
  arrayNullable: boolean;
}

export const ACQUISITION: Readonly<Record<Acquisition, AcquisitionInfo>> = {
  heart_rate: { module: "Toybox.ActivityMonitor", call: "", newestFirst: false, arrayNullable: false },
  activity_history: { module: "Toybox.ActivityMonitor", call: "ActivityMonitor.getHistory()", newestFirst: true, arrayNullable: false },
  hourly_forecast: { module: "Toybox.Weather", call: "Weather.getHourlyForecast()", newestFirst: false, arrayNullable: true },
  daily_forecast: { module: "Toybox.Weather", call: "Weather.getDailyForecast()", newestFirst: false, arrayNullable: true },
};

export interface SeriesDef {
  name: string;
  acquisition: Acquisition;
  /** The field read off one entry; `null` for `heart_rate`, whose value is the reader. */
  field_name: string | null;
  value_type: "number" | "float";
  /** A nullable intermediate object on a dotted `field_name` (`activeMinutes`). */
  intermediate: string | null;
  /** Seconds between entries; `null` for `heart_rate`, whose interval is device dependent. */
  interval_seconds: number | null;
  /** The SDK's documented cap on the array, or `null` where none is documented. */
  max_count: number | null;
  unit: string | null;
  doc: string;
  source_ref: string;
}

const s = (name: string, acquisition: Acquisition, field_name: string | null, value_type: "number" | "float",
  intermediate: string | null, interval_seconds: number | null, max_count: number | null, unit: string | null,
  doc: string, source_ref: string): SeriesDef =>
  ({ name, acquisition, field_name, value_type, intermediate, interval_seconds, max_count, unit, doc, source_ref });

export const SERIES: Catalogue<SeriesDef> = new Catalogue([
  s("heart_rate", "heart_rate", null, "number", null, null, null, "bpm",
    "heart rate history -- a Duration range bins by time; a count range reads the last N samples raw",
    "Toybox/ActivityMonitor.html#getHeartRateHistory-instance_method"),
  s("steps", "activity_history", "steps", "number", null, 86400, 7, null,
    "steps per day, up to 7 days, newest first", "Toybox/ActivityMonitor/History.html"),
  s("calories", "activity_history", "calories", "number", null, 86400, 7, "kcal",
    "calories burned per day, up to 7 days", "Toybox/ActivityMonitor/History.html"),
  s("distance", "activity_history", "distance", "number", null, 86400, 7, "cm",
    "distance per day, up to 7 days", "Toybox/ActivityMonitor/History.html"),
  s("floors_climbed", "activity_history", "floorsClimbed", "number", null, 86400, 7, null,
    "floors climbed per day, up to 7 days", "Toybox/ActivityMonitor/History.html"),
  s("active_minutes", "activity_history", "activeMinutes.total", "number", "activeMinutes", 86400, 7, "minutes",
    "active minutes per day, up to 7 days -- activeMinutes itself is nullable, .total on it is not",
    "Toybox/ActivityMonitor/History.html, Toybox/ActivityMonitor/ActiveMinutes.html"),
  s("forecast_temperature", "hourly_forecast", "temperature", "float", null, 3600, null, "celsius",
    "hourly forecast temperature", "Toybox/Weather/HourlyForecast.html"),
  s("forecast_precipitation_chance", "hourly_forecast", "precipitationChance", "number", null, 3600, null, "percent",
    "hourly forecast chance of precipitation, 0-100", "Toybox/Weather/HourlyForecast.html"),
  s("forecast_cloud_cover", "hourly_forecast", "cloudCover", "number", null, 3600, null, "percent",
    "hourly forecast cloud cover, 0-100", "Toybox/Weather/HourlyForecast.html"),
  s("forecast_uv_index", "hourly_forecast", "uvIndex", "float", null, 3600, null, null,
    "hourly forecast UV index, 0-10", "Toybox/Weather/HourlyForecast.html"),
  s("forecast_wind_speed", "hourly_forecast", "windSpeed", "float", null, 3600, null, "m/s",
    "hourly forecast wind speed", "Toybox/Weather/HourlyForecast.html"),
  s("forecast_humidity", "hourly_forecast", "relativeHumidity", "number", null, 3600, null, "percent",
    "hourly forecast relative humidity, 0-100", "Toybox/Weather/HourlyForecast.html"),
  s("daily_high_temperature", "daily_forecast", "highTemperature", "float", null, 86400, null, "celsius",
    "daily forecast high temperature", "Toybox/Weather/DailyForecast.html"),
  s("daily_low_temperature", "daily_forecast", "lowTemperature", "float", null, 86400, null, "celsius",
    "daily forecast low temperature", "Toybox/Weather/DailyForecast.html"),
  s("daily_precipitation_chance", "daily_forecast", "precipitationChance", "number", null, 86400, null, "percent",
    "daily forecast chance of precipitation, 0-100", "Toybox/Weather/DailyForecast.html"),
].map((def) => [def.name, def]));

/** Why a quantity a watch face cannot plot as a history is unavailable, keyed by name. */
const SENSOR_HISTORY = "Toybox.SensorHistory is the only API that serves it as a history, "
  + "and a watch face may not declare that permission -- "
  + "Core_Topics/Manifest_and_Permissions.html gives SensorHistory an "
  + "empty 'Watch Face' column";
const NO_SOLAR = "there is no solar history API anywhere in Connect IQ -- solar is "
  + "only ever a current reading (System.Stats.solarIntensity, "
  + "Complications.COMPLICATION_TYPE_SOLAR_INPUT), so the chart on a "
  + "stock Garmin face is native firmware this API does not expose";
export const UNAVAILABLE: ReadonlyMap<string, string> = new Map([
  ...["pressure", "barometric_pressure", "stress", "elevation", "altitude",
    "body_battery", "oxygen_saturation", "pulse_ox", "temperature"].map((n): [string, string] => [n, SENSOR_HISTORY]),
  ...["solar", "solar_input", "solar_intensity", "solar_charge"].map((n): [string, string] => [n, NO_SOLAR]),
]);

/**
 * Why a plausible-but-impossible series name cannot be plotted, or `null`:
 * matched on the bare name and its last dotted segment, and on its last
 * underscored segment only when it is not a near miss of a real series.
 */
export function unavailableReason(name: string): string | null {
  const found = UNAVAILABLE.get(name);
  if (found !== undefined) return found;
  const dotted = name.slice(name.lastIndexOf(".") + 1);
  const byDotted = UNAVAILABLE.get(dotted);
  if (byDotted !== undefined) return byDotted;
  if (SERIES.suggest(name).length > 0) return null;
  return UNAVAILABLE.get(dotted.slice(dotted.lastIndexOf("_") + 1)) ?? null;
}

export function get(name: string): SeriesDef | undefined {
  return SERIES.get(name);
}

export function names(): string[] {
  return [...SERIES.keys()].sort();
}
