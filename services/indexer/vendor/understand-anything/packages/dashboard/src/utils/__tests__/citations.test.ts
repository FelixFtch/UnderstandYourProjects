import { describe, it, expect } from "vitest";
import { parseTrailingCitation, splitInlineCitations } from "../citations";

describe("parseTrailingCitation", () => {
  it("splits a verified trailing range off a key point", () => {
    expect(parseTrailingCitation("[fact] The router dispatches by version (L97-L215)")).toEqual({
      body: "[fact] The router dispatches by version",
      citation: { lineStart: 97, lineEnd: 215, verified: true, label: "L97-L215" },
    });
  });

  it("flags unverified ranges", () => {
    const parsed = parseTrailingCitation("Point copied from the model (unverified L40-L52)");
    expect(parsed?.body).toBe("Point copied from the model");
    expect(parsed?.citation.verified).toBe(false);
    expect(parsed?.citation.label).toBe("unverified L40-L52");
    expect(parsed?.citation.lineStart).toBe(40);
    expect(parsed?.citation.lineEnd).toBe(52);
  });

  it("accepts component-style labels", () => {
    expect(parseTrailingCitation("route_fast (L97-L215)")).toEqual({
      body: "route_fast",
      citation: { lineStart: 97, lineEnd: 215, verified: true, label: "L97-L215" },
    });
  });

  it("keeps raw text when nothing parses", () => {
    expect(parseTrailingCitation("Plain summary without a range")).toBeNull();
    expect(parseTrailingCitation("Symbol name route_fast")).toBeNull();
    expect(parseTrailingCitation("")).toBeNull();
  });

  it("does not treat a lone range as a citation-bearing point", () => {
    expect(parseTrailingCitation("(L1-L9)")).toBeNull();
    expect(parseTrailingCitation("(unverified L1-L9)")).toBeNull();
  });
});

describe("splitInlineCitations", () => {
  it("chips inline path citations and keeps the surrounding text", () => {
    const segments = splitInlineCitations("Implemented in services/agent.py (L40-L52) and shared.");
    expect(segments).toHaveLength(3);
    expect(segments[0]).toEqual({ text: "Implemented in " });
    expect(segments[1]).toEqual({
      text: "services/agent.py",
      citation: { file: "services/agent.py", lineStart: 40, lineEnd: 52, verified: true, label: "L40-L52" },
    });
    expect(segments[2]).toEqual({ text: " and shared." });
  });

  it("carries the unverified marker and the anchor token", () => {
    const segments = splitInlineCitations("see route_fast (unverified L9-L18)");
    expect(segments).toHaveLength(2);
    expect(segments[0]).toEqual({ text: "see " });
    expect(segments[1].citation?.verified).toBe(false);
    expect(segments[1].citation?.file).toBe("route_fast");
    expect(segments[1].citation?.label).toBe("unverified L9-L18");
  });

  it("returns the body untouched when no citation is present", () => {
    expect(splitInlineCitations("No citations here, just an answer.")).toEqual([{ text: "No citations here, just an answer." }]);
    expect(splitInlineCitations("")).toEqual([]);
  });

  it("handles several citations in one answer", () => {
    const segments = splitInlineCitations("a.py (L1-L2), then b.py (unverified L3-L4).");
    const chips = segments.filter((segment) => segment.citation);
    expect(chips).toHaveLength(2);
    expect(chips[0].citation?.label).toBe("L1-L2");
    expect(chips[1].citation?.label).toBe("unverified L3-L4");
  });

  it("keeps plain parenthetical sentences intact", () => {
    expect(splitInlineCitations("The queue (bounded, single pass) stays fail-closed.")).toEqual([
      { text: "The queue (bounded, single pass) stays fail-closed." },
    ]);
  });
});
