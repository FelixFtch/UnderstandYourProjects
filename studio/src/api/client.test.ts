// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FlowEvent } from "./contracts";
import { ApiError, getToken, onAuthLost, setToken, streamEvents } from "./client";

/** A fake text/event-stream body that yields the given chunks (strings may split frames anywhere). */
function sseResponse(chunks: string[], status = 200): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
});

describe("streamEvents (SSE parsing)", () => {
  it("parses frames split across chunks, CRLF, comments and junk", async () => {
    const fetchMock = vi.fn(async () => sseResponse([
      ': keep-alive\n\ndata: {"type":"trace","node":"iden',
      'tity","status":"start","detail":"","ms":0}\r\n\r\n',
      'data: {"type":"sentence","text":"Hello."}\n\ndata: not json\n\n',
      'event: ignored\ndata:{"type":"sentence","text":"World."}\n\n',
      'data: {"type":"final","reply":"Hello. World."}\n\n',
    ]));
    vi.stubGlobal("fetch", fetchMock);
    setToken("cat_test");
    const events: FlowEvent[] = [];
    await streamEvents("/api/studio/threads/jarvis/messages", { text: "hi" }, (e) => events.push(e));

    expect(events.map((e) => e.type)).toEqual(["trace", "sentence", "sentence", "final"]);
    expect(events[0]).toMatchObject({ node: "identity", status: "start" });
    expect(events[2]).toMatchObject({ text: "World." });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer cat_test");
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
  });

  it("delivers a final frame that has no trailing newline", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(['data: {"type":"sentence","text":"a"}\n', 'data: {"type":"final","reply":"a"}'])));
    const events: FlowEvent[] = [];
    await streamEvents("/x", {}, (e) => events.push(e));
    expect(events.map((e) => e.type)).toEqual(["sentence", "final"]);
  });

  it("handles a multi-byte character split between chunks", async () => {
    const bytes = new TextEncoder().encode('data: {"type":"sentence","text":"你好"}\n\n');
    const cut = bytes.length - 6; // inside the second CJK character
    const body = new ReadableStream<Uint8Array>({
      start(c) { c.enqueue(bytes.slice(0, cut)); c.enqueue(bytes.slice(cut)); c.close(); },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const events: FlowEvent[] = [];
    await streamEvents("/x", {}, (e) => events.push(e));
    expect(events).toEqual([{ type: "sentence", text: "你好" }]);
  });

  it("on 401 clears the token, notifies the shell and throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 401 })));
    setToken("cat_old");
    const lost = vi.fn();
    const off = onAuthLost(lost);
    await expect(streamEvents("/x", {}, () => {})).rejects.toBeInstanceOf(ApiError);
    expect(lost).toHaveBeenCalledTimes(1);
    expect(getToken()).toBeNull();
    off();
  });

  it("keeps the login when a feature endpoint says 401 but HomeHub still accepts the token", async () => {
    // 2026-10-11: a backend's own 401 (project service) signed the owner out.
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      String(url).endsWith("/api/studio/me")
        ? new Response(JSON.stringify({ member_id: "robin" }), { status: 200 })
        : new Response(JSON.stringify({ error: "invalid_credentials" }), { status: 401 })));
    setToken("cat_keep");
    const lost = vi.fn();
    const off = onAuthLost(lost);
    await expect(streamEvents("/api/studio/projects", {}, () => {})).rejects.toBeInstanceOf(ApiError);
    expect(lost).not.toHaveBeenCalled();
    expect(getToken()).toBe("cat_keep");
    off();
  });
});
