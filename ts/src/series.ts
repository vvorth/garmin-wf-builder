// The `series:` a `graph` element may plot, and how each is read on the
// device. Port of wfb/series.py's tables; its unknown-name suggestions
// (`unavailable_reason`, difflib) come with the catalogue port.
//
// Every field name and "or Null" was checked against the SDK's own docs
// (`Toybox/ActivityMonitor.html`, `.../ActivityMonitor/History.html`,
// `.../ActivityMonitor/ActiveMinutes.html`, `Toybox/Weather/HourlyForecast.html`,
// `Toybox/Weather/DailyForecast.html`), as wfb/series.py records.

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
  fieldName: string | null;
  valueType: "number" | "float";
  /** A nullable intermediate object on a dotted `fieldName` (`activeMinutes`). */
  intermediate: string | null;
  /** Seconds between entries; `null` for `heart_rate`, whose interval is device dependent. */
  intervalSeconds: number | null;
  /** The SDK's documented cap on the array, or `null` where none is documented. */
  maxCount: number | null;
  unit: string | null;
  doc: string;
  sourceRef: string;
}

const s = (name: string, acquisition: Acquisition, fieldName: string | null, valueType: "number" | "float",
  intermediate: string | null, intervalSeconds: number | null, maxCount: number | null, unit: string | null,
  doc: string, sourceRef: string): SeriesDef =>
  ({ name, acquisition, fieldName, valueType, intermediate, intervalSeconds, maxCount, unit, doc, sourceRef });

export const SERIES: ReadonlyMap<string, SeriesDef> = new Map([
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

export function get(name: string): SeriesDef | undefined {
  return SERIES.get(name);
}

export function names(): string[] {
  return [...SERIES.keys()].sort();
}
