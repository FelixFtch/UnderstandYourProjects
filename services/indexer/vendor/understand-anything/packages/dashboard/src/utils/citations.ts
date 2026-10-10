/**
 * Citation parsing for the v3.2 anchored enrichment format.
 *
 * Enriched KnowledgeItems end key points and component labels with a
 * symbol-snapped range — "(L97-L215)" — or "(unverified L40-L52)" when no
 * symbol overlapped, and the search synthesis copies those tokens inline as
 * "path (Lx-Ly)". These helpers split the citation off without rewriting the
 * surrounding text, and return null/unchanged segments when nothing parses.
 */
export interface Citation {
  /** Anchor text (path or symbol) for inline citations; bare trailing ranges leave it unset. */
  file?: string;
  lineStart: number;
  lineEnd?: number;
  /** False when the enrichment marked the range "(unverified Lx-Ly)". */
  verified: boolean;
  /** Chip label, e.g. "L97-L215" or "unverified L40-L52". */
  label: string;
}

const RANGE = String.raw`L(\d{1,4})(?:\s*[-–]\s*L?(\d{1,4}))?`;
const TRAILING = new RegExp(String.raw`\s*\(\s*(unverified\s+)?${RANGE}\s*\)\s*$`, "i");
const INLINE = new RegExp(String.raw`(\S+)\s*\(\s*(unverified\s+)?${RANGE}\s*\)`, "gi");

function toCitation(unverified: string | undefined, lineStart: string, lineEnd: string | undefined, file?: string): Citation {
  const verified = !unverified;
  const start = Number(lineStart);
  const end = lineEnd === undefined ? undefined : Number(lineEnd);
  return {
    file,
    lineStart: start,
    lineEnd: end,
    verified,
    label: `${verified ? "" : "unverified "}L${start}${end === undefined ? "" : `-L${end}`}`,
  };
}

/** Split a trailing "(Lx-Ly)" / "(unverified Lx-Ly)" citation off a key point, label, or summary. */
export function parseTrailingCitation(value: string): { body: string; citation: Citation } | null {
  if (!value) return null;
  const match = TRAILING.exec(value);
  if (!match) return null;
  const body = value.slice(0, match.index).trim();
  // A lone "(L1-L9)" is a range, not a citation-bearing point; keep it raw.
  if (!body) return null;
  return { body, citation: toCitation(match[1], match[2], match[3]) };
}

/** Split an answer body into plain text and inline "path (Lx-Ly)" citation segments. */
export function splitInlineCitations(value: string): Array<{ text: string; citation?: Citation }> {
  if (!value) return [];
  const segments: Array<{ text: string; citation?: Citation }> = [];
  let lastIndex = 0;
  INLINE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = INLINE.exec(value)) !== null) {
    if (match.index > lastIndex) segments.push({ text: value.slice(lastIndex, match.index) });
    segments.push({ text: match[1], citation: toCitation(match[2], match[3], match[4], match[1]) });
    lastIndex = INLINE.lastIndex;
  }
  if (lastIndex < value.length) segments.push({ text: value.slice(lastIndex) });
  return segments;
}
