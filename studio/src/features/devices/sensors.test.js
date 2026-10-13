import { describe, expect, it } from "vitest";
import { buildLine, buildPresenceBand, fmtValue, formatDuration, isPositive, numericPoints, parseState, pickPresenceHero, readingStatus, sortSensorDevices, } from "./sensors";
const row = (entity_id, state, attributes = {}) => ({ entity_id, state, attributes, last_changed: "2026-10-12T20:00:00-04:00" });
describe("readingStatus", () => {
    it("prefers unavailable over stale over ok", () => {
        expect(readingStatus(row("s.a", "unavailable", { stale: true }))).toBe("unavailable");
        expect(readingStatus(row("s.a", "21.5", { stale: true }))).toBe("stale");
        expect(readingStatus(row("s.a", "21.5"))).toBe("ok");
    });
});
describe("isPositive", () => {
    it("matches the hub's occupied vocabulary, case-insensitively", () => {
        expect(isPositive("on")).toBe(true);
        expect(isPositive("Person")).toBe(true);
        expect(isPositive("occupied")).toBe(true);
        expect(isPositive("off")).toBe(false);
        expect(isPositive("")).toBe(false);
    });
});
describe("pickPresenceHero", () => {
    const dev = (entities) => ({ device_id: "d", name: "d", category: "presence", entities, entity_count: entities.length, online: true, readings: [] });
    it("prefers a person/motion entity id, then any presence-classified row, then the first row", () => {
        const states = new Map([
            ["sensor.radar_score", row("sensor.radar_score", "0.8", { category: "presence" })],
            ["binary_sensor.radar_person", row("binary_sensor.radar_person", "on", { category: "presence" })],
        ]);
        expect(pickPresenceHero(dev(["sensor.radar_score", "binary_sensor.radar_person"]), states)?.entity_id).toBe("binary_sensor.radar_person");
        const states2 = new Map([
            ["sensor.x", row("sensor.x", "1", { category: "presence" })],
            ["sensor.y", row("sensor.y", "2", {})],
        ]);
        expect(pickPresenceHero(dev(["sensor.y", "sensor.x"]), states2)?.entity_id).toBe("sensor.x");
        const states3 = new Map([["sensor.z", row("sensor.z", "3", {})]]);
        expect(pickPresenceHero(dev(["sensor.z"]), states3)?.entity_id).toBe("sensor.z");
    });
    it("returns null when the device has no known entities", () => {
        expect(pickPresenceHero(dev(["sensor.gone"]), new Map())).toBeNull();
    });
});
describe("sortSensorDevices", () => {
    it("puts online devices first, then category order, then name", () => {
        const mk = (device_id, name, category, online) => ({ device_id, name, category, online, entities: [], entity_count: 0, readings: [] });
        const sorted = sortSensorDevices([
            mk("z", "Z Door", "other", true),
            mk("r", "Radar", "presence", false),
            mk("a", "Air A", "air_quality", true),
            mk("b", "Air B", "air_quality", true),
        ]);
        expect(sorted.map((d) => d.device_id)).toEqual(["a", "b", "z", "r"]);
    });
});
describe("numericPoints / parseState", () => {
    it("keeps only finite ts+value pairs", () => {
        const pts = numericPoints([
            { ts: "2026-10-12T19:00:00-04:00", state: "552.0" },
            { ts: "not a date", state: "1" },
            { ts: "2026-10-12T20:00:00-04:00", state: "unavailable" },
        ]);
        expect(pts).toHaveLength(1);
        expect(pts[0].v).toBe(552);
        expect(parseState("497.0")).toBe(497);
        expect(Number.isNaN(parseState("unavailable"))).toBe(true);
    });
});
describe("buildLine", () => {
    it("draws one coordinate pair per point and reports the bounds", () => {
        const t0 = Date.parse("2026-10-12T00:00:00Z");
        const geo = buildLine([
            { t: t0, v: 10 },
            { t: t0 + 60_000, v: 20 },
            { t: t0 + 120_000, v: 15 },
        ], 260, 64);
        expect(geo).not.toBeNull();
        expect(geo.points.split(" ")).toHaveLength(3);
        expect(geo.lo).toBe(10);
        expect(geo.hi).toBe(20);
        expect(geo.area.endsWith("Z")).toBe(true);
    });
    it("needs two points and survives a flat series", () => {
        expect(buildLine([{ t: 0, v: 1 }])).toBeNull();
        const flat = buildLine([
            { t: 0, v: 5 },
            { t: 1, v: 5 },
        ]);
        expect(flat).not.toBeNull();
        expect(flat.lo).toBe(5);
        expect(flat.hi).toBe(5);
    });
});
describe("buildPresenceBand", () => {
    const h = (n) => new Date(2026, 9, 12, n, 0, 0).toISOString();
    const start = new Date(2026, 9, 11, 21, 0, 0);
    const end = new Date(2026, 9, 12, 21, 0, 0);
    it("merges consecutive occupied samples into one span and keeps the open tail", () => {
        const band = buildPresenceBand([
            { ts: h(9), state: "off" },
            { ts: h(10), state: "on" },
            { ts: h(10.5), state: "on" }, // same occupied run: must merge, not double-count
            { ts: h(11), state: "off" },
            { ts: h(20), state: "on" }, // still occupied now
        ], start, end);
        expect(band.count).toBe(2);
        expect(band.spans[0][1] - band.spans[0][0]).toBe(60 * 60_000);
        expect(band.spans[1][1]).toBe(end.getTime());
    });
    it("clamps spans to the window", () => {
        const band = buildPresenceBand([
            { ts: new Date(2026, 9, 11, 18, 0, 0).toISOString(), state: "on" }, // occupied before the window
            { ts: h(3), state: "off" },
        ], start, end);
        expect(band.count).toBe(1);
        expect(band.spans[0][0]).toBe(start.getTime());
        expect(band.spans[0][1]).toBe(new Date(2026, 9, 12, 3, 0, 0).getTime());
    });
    it("counts nothing when never occupied", () => {
        const band = buildPresenceBand([{ ts: h(9), state: "off" }, { ts: h(10), state: "off" }], start, end);
        expect(band.spans).toEqual([]);
        expect(band.totalMs).toBe(0);
    });
});
describe("format helpers", () => {
    it("formatDuration renders minutes and hours", () => {
        expect(formatDuration(45 * 60_000)).toBe("45 m");
        expect(formatDuration(205 * 60_000)).toBe("3 h 25 m");
        expect(formatDuration(0)).toBe("0 m");
    });
    it("fmtValue keeps stable decimals per magnitude", () => {
        expect(fmtValue(497.4)).toBe("497");
        expect(fmtValue(25.11)).toBe("25.1");
        expect(fmtValue(0.351)).toBe("0.35");
        expect(fmtValue(Number.NaN)).toBe("–");
    });
});
