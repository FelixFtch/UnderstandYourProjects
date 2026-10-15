import { afterEach, describe, expect, it } from "vitest";
import { studioAuthHeaders } from "../studio-api";

function installSessionStorage(token: string | null): void {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      sessionStorage: {
        getItem: () => token,
      },
    },
  });
}

afterEach(() => {
  delete (globalThis as Record<string, unknown>).window;
});

describe("studioAuthHeaders", () => {
  it("forwards the existing dashboard session as a bearer token", () => {
    installSessionStorage("homehub-session");
    expect(studioAuthHeaders()).toEqual({ Authorization: "Bearer homehub-session" });
  });

  it("does not turn the demo sentinel into an authorization header", () => {
    installSessionStorage("__demo__");
    expect(studioAuthHeaders()).toEqual({});
  });

  it("fails closed when session storage is unavailable", () => {
    expect(studioAuthHeaders()).toEqual({});
  });
});
