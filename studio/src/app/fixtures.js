let enrolled = false;
export function me() {
    return {
        member_id: "robin",
        role: "owner",
        display_name: "Robin",
        household_id: "household",
        jarvis: {
            node_id: "hub_7f3c2a91",
            display_name: "Robin's Jarvis",
            number: "J-4829-1300",
            urn: "urn:ai:domain:clinic.jarvis.local:robin",
            town: { run_id: "run-2026-10-11", participant: "clinic" },
        },
        agent_box: enrolled ? { enrolled: true, box_id: "box_q8Zt1fKx" } : { enrolled: false, box_id: null },
    };
}
export function pair(code) {
    if (code.toUpperCase() === "00000000")
        throw new Error("Unknown or already-used pairing code");
    return { token: "cat_fixture_token", member_id: "robin", role: "owner", display_name: "Robin" };
}
export function enroll() {
    enrolled = true;
    return { enrolled: true, box_id: "box_q8Zt1fKx" };
}
export const delay = (ms) => new Promise((r) => setTimeout(r, ms));
