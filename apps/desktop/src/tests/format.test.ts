import {
  formatApplicationDate,
  formatApplicationDateTime,
  formatApplicationTimestamp,
  formatCount,
  formatScientificNumber,
  formatSignedScientificNumber,
} from "../utils/format";

it("uses an invariant dot decimal and unambiguous scientific grouping", () => {
  expect(formatScientificNumber(5620.94, {
    maximumFractionDigits: 1,
    groupThousands: true,
  })).toBe("5\u202f620.9");
  expect(formatScientificNumber(-7.51, 3)).toBe("-7.510");
  expect(formatScientificNumber(-0.0001, 3)).toBe("0.000");
  expect(formatCount(102600)).toBe("102\u202f600");
});

it("keeps missing or non-finite scientific values explicit", () => {
  expect(formatScientificNumber(null, 2)).toBe("—");
  expect(formatScientificNumber(Number.NaN, 2)).toBe("—");
  expect(formatSignedScientificNumber(1.25, 2)).toBe("+1.25");
  expect(formatSignedScientificNumber(0.0001, 3)).toBe("0.000");
});

it("uses one English application date language with local 24-hour time", () => {
  expect(formatApplicationDate("2026-08-28T12:34:00")).toBe("28 Aug 2026");
  expect(formatApplicationDateTime("2026-08-28T12:34:00")).toBe("28 Aug 2026, 12:34");
  expect(formatApplicationTimestamp("2026-08-28T12:34:56")).toBe(
    "28 Aug 2026, 12:34:56",
  );
});

it("preserves an invalid recorded timestamp instead of inventing a date", () => {
  expect(formatApplicationDateTime("not-recorded")).toBe("not-recorded");
});
