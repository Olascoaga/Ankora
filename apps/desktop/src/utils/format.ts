const APPLICATION_LOCALE = "en-GB";
const SCIENTIFIC_LOCALE = "en-US";
const NARROW_NO_BREAK_SPACE = "\u202f";
const NOT_RECORDED = "—";

interface ScientificNumberOptions {
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
  groupThousands?: boolean;
}

const scientificFormatters = new Map<string, Intl.NumberFormat>();

const applicationDateFormatter = new Intl.DateTimeFormat(APPLICATION_LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const applicationDateTimeFormatter = new Intl.DateTimeFormat(APPLICATION_LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const applicationTimestampFormatter = new Intl.DateTimeFormat(APPLICATION_LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/**
 * Render a scientific value with a stable dot decimal, independent of the
 * Windows display language. A numeric second argument requests fixed decimal
 * places; the object form allows a trimmed range and optional unambiguous thin
 * space grouping for large values.
 */
export function formatScientificNumber(
  value: number | null | undefined,
  precision: number | ScientificNumberOptions,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NOT_RECORDED;

  const options = typeof precision === "number"
    ? { minimumFractionDigits: precision, maximumFractionDigits: precision }
    : precision;
  const minimumFractionDigits = options.minimumFractionDigits ?? 0;
  const maximumFractionDigits = options.maximumFractionDigits ?? minimumFractionDigits;
  const groupThousands = options.groupThousands ?? false;
  const key = `${minimumFractionDigits}:${maximumFractionDigits}:${groupThousands}`;
  let formatter = scientificFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(SCIENTIFIC_LOCALE, {
      minimumFractionDigits,
      maximumFractionDigits,
      useGrouping: groupThousands,
    });
    scientificFormatters.set(key, formatter);
  }

  const zeroThreshold = 0.5 * 10 ** -maximumFractionDigits;
  const normalized = Math.abs(value) < zeroThreshold ? 0 : value;
  return formatter.format(normalized).replaceAll(",", NARROW_NO_BREAK_SPACE);
}

export function formatSignedScientificNumber(
  value: number | null | undefined,
  precision: number,
): string {
  const formatted = formatScientificNumber(value, precision);
  const roundedValue = Number(formatted.replaceAll(NARROW_NO_BREAK_SPACE, ""));
  return formatted !== NOT_RECORDED && Number.isFinite(roundedValue) && roundedValue > 0
    ? `+${formatted}`
    : formatted;
}

export function formatCount(value: number | null | undefined): string {
  return formatScientificNumber(value, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
    groupThousands: true,
  });
}

export function formatApplicationDate(value: string): string {
  return formatApplicationMoment(value, applicationDateFormatter);
}

export function formatApplicationDateTime(value: string): string {
  return formatApplicationMoment(value, applicationDateTimeFormatter);
}

export function formatApplicationTimestamp(value: string): string {
  return formatApplicationMoment(value, applicationTimestampFormatter);
}

function formatApplicationMoment(value: string, formatter: Intl.DateTimeFormat): string {
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? value : formatter.format(moment);
}
