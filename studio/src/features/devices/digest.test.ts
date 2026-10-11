// @vitest-environment node
import { describe, expect, it } from "vitest";
import { bucketChanges, dayBars, hierarchyPhrases, statusMeta, tierMeta } from "./digest";

const now = new Date(2026, 9, 11, 15, 0, 0); // Sun Oct 11 2026, 15:00 local
const at = (daysAgo: number, hour = 10) => new Date(2026, 9, 11 - daysAgo, hour, 0, 0).toISOString();

describe("bucketChanges", () => {
  it("groups by calendar day, newest first, skipping empty buckets", () => {
    const groups = bucketChanges([
      { file: "old.py", mtime: at(12), purpose: "" },
      { file: "y1.py", mtime: at(1, 9), purpose: "" },
      { file: "t.py", mtime: at(0, 8), purpose: "" },
      { file: "y2.py", mtime: at(1, 22), purpose: "" },
      { file: "w.py", mtime: at(4), purpose: "" },
      { file: "bad.py", mtime: "not a date", purpose: "" },
    ], now);
    expect(groups.map((g) => g.label)).toEqual(["Today", "Yesterday", "Earlier this week", "Earlier"]);
    expect(groups[1].items.map((i) => i.file)).toEqual(["y2.py", "y1.py"]);
    expect(groups[3].items.map((i) => i.file).sort()).toEqual(["bad.py", "old.py"]);
  });
  it("returns nothing for no changes", () => {
    expect(bucketChanges([], now)).toEqual([]);
  });
});

describe("dayBars", () => {
  it("fills a contiguous 7-day window ending today", () => {
    const bars = dayBars([{ date: "2026-10-10", count: 6 }, { date: "2026-10-05", count: 1 }, { date: "2026-09-01", count: 9 }, { date: "2026-10-10", count: 1 }], now);
    expect(bars).toHaveLength(7);
    expect(bars[0].date).toBe("2026-10-05");
    expect(bars[6]).toMatchObject({ date: "2026-10-11", count: 0, isToday: true, label: "Today" });
    expect(bars.map((b) => b.count)).toEqual([1, 0, 0, 0, 0, 7, 0]);
  });
});

describe("labels", () => {
  it("maps statuses, tiers and hierarchy phrases", () => {
    expect(statusMeta("analyzing")).toMatchObject({ label: "Analyzing", pulse: true });
    expect(statusMeta("weird").label).toBe("weird");
    expect(tierMeta("A").hint).toMatch(/Key file/);
    expect(tierMeta("gate").tone).toBe("warn");
    expect(hierarchyPhrases("commontasks", 0)).toEqual(["inside commontasks"]);
    expect(hierarchyPhrases(null, 3)).toEqual(["contains 3 folders"]);
    expect(hierarchyPhrases("code", 1)).toEqual(["inside code", "contains 1 folder"]);
  });
});
