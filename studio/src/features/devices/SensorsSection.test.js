import { jsx as _jsx } from "react/jsx-runtime";
// The Sensors section inside DevicesPage: renders hub devices + reserved
// placeholders from /api/sensors/*, opens a detail at #/devices/sensors/<id>.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DevicesPage from "./DevicesPage";
const SENSORS_DEVICES = {
    count: 2,
    devices: [
        {
            device_id: "air_station", name: "Air Station", manufacturer: "Seeed", model: "XIAO + SCD41",
            category: "air_quality", entities: ["sensor.air_station_co2"], entity_count: 1, online: true,
            unavailable: 0, stale: 0, last_changed: new Date().toISOString(),
            readings: [{ entity_id: "sensor.air_station_co2", label: "CO2", value: "497.0", unit: "ppm", category: "air_quality" }],
        },
        {
            device_id: "radar_1", name: "Room Radar", category: "presence",
            entities: ["binary_sensor.radar_1_person"], entity_count: 1, online: true,
            readings: [{ entity_id: "binary_sensor.radar_1_person", label: "Person State", value: "on" }],
        },
    ],
    placeholders: [{ category: "lighting", note: "Waiting for the StampPLC firmware to dual-publish MQTT." }],
};
const SENSORS_STATES = [
    { entity_id: "sensor.air_station_co2", state: "497.0", attributes: { friendly_name: "CO2", category: "air_quality", device_id: "air_station", unit_of_measurement: "ppm" }, last_changed: new Date().toISOString() },
    { entity_id: "binary_sensor.radar_1_person", state: "on", attributes: { friendly_name: "Person State", category: "presence", device_id: "radar_1" }, last_changed: new Date().toISOString() },
];
let handler;
beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
        const r = handler(url);
        const status = r?.status ?? 404;
        const body = r?.body ?? { detail: "not in this test" };
        return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    }));
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});
function renderPage(param) {
    const navigate = vi.fn();
    render(_jsx(DevicesPage, { param: param, navigate: navigate }));
    return navigate;
}
describe("DevicesPage sensors section", () => {
    it("renders sensor cards and reserved placeholders from /api/sensors/devices", async () => {
        handler = (url) => {
            if (url === "/api/studio/devices")
                return { status: 200, body: { devices: [] } };
            if (url === "/api/studio/projects")
                return { status: 200, body: { projects: [], tree: [] } };
            if (url === "/api/sensors/devices")
                return { status: 200, body: SENSORS_DEVICES };
            if (url === "/api/sensors/states")
                return { status: 200, body: SENSORS_STATES };
            return undefined;
        };
        renderPage();
        expect(await screen.findByText("Air Station")).toBeTruthy();
        expect(screen.getByText("CO2")).toBeTruthy();
        expect(screen.getByText("Room Radar")).toBeTruthy();
        expect(screen.getByText("Someone is there now")).toBeTruthy(); // presence hero reads /api/sensors/states
        expect(screen.getByText("Waiting for the StampPLC firmware to dual-publish MQTT.")).toBeTruthy();
        expect(screen.getByText("2 devices", { exact: false })).toBeTruthy();
    });
    it("opens a sensor detail at #/devices/sensors/<id> and keeps the project digest route free", async () => {
        handler = (url) => {
            if (url === "/api/studio/devices")
                return { status: 200, body: { devices: [] } };
            if (url === "/api/studio/projects")
                return { status: 200, body: { projects: [], tree: [] } };
            if (url === "/api/sensors/devices")
                return { status: 200, body: SENSORS_DEVICES };
            if (url === "/api/sensors/states")
                return { status: 200, body: SENSORS_STATES };
            if (url.startsWith("/api/sensors/entities/sensor.air_station_co2/history")) {
                return { status: 200, body: { entity_id: "sensor.air_station_co2", hours: 24, count: 2, points: [
                            { ts: new Date(Date.now() - 7200_000).toISOString(), state: "552.0" },
                            { ts: new Date().toISOString(), state: "497.0" },
                        ] } };
            }
            return undefined;
        };
        const navigate = renderPage();
        fireEvent.click(await screen.findByText("Air Station"));
        expect(navigate).toHaveBeenCalledWith("#/devices/sensors/air_station");
        // the detail route itself: charts load per metric, back link returns to #/devices
        cleanup();
        const nav2 = renderPage("sensors/air_station");
        expect(await screen.findByText("CO2")).toBeTruthy();
        expect(await screen.findByText(/Collecting|552/)).toBeTruthy();
        const back = screen.getByText("Devices", { selector: "nav a" });
        fireEvent.click(back);
        expect(nav2).toHaveBeenCalledWith("#/devices");
    });
    it("shows the hub-unreachable error without dropping the rest of the page", async () => {
        handler = (url) => {
            if (url === "/api/studio/devices")
                return { status: 200, body: { devices: [] } };
            if (url === "/api/studio/projects")
                return { status: 200, body: { projects: [], tree: [] } };
            if (url === "/api/sensors/devices" || url === "/api/sensors/states") {
                return { status: 503, body: { detail: { error: "sensor_hub_unreachable", message: "The sensor hub is not reachable." } } };
            }
            return undefined;
        };
        renderPage();
        // describeError maps 503 to "<service> unreachable" (its own title wins)
        expect(await screen.findByText("Sensor hub unreachable")).toBeTruthy();
    });
});
