import type { Citation } from "../utils/citations";

/**
 * Reflect a citation as a copyable deep link (?file=&lines=) without any
 * backend state. replaceState keeps the URL shareable without spamming
 * browser history.
 */
export function citationDeepLink(citation: Citation, file?: string): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  const lines = `${citation.lineStart}${citation.lineEnd === undefined ? "" : `-${citation.lineEnd}`}`;
  params.set("lines", lines);
  if (file) params.set("file", file);
  const search = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`);
}

/**
 * Monospace citation chip: green when the enrichment snapped the range to a
 * real symbol, amber when it was marked "(unverified …)". Rendered as a span
 * so it stays valid inside the evidence card's button; clicking only writes
 * the deep link and never rewrites content or triggers the card action.
 */
export default function CitationChip({ citation, file }: { citation: Citation; file?: string }) {
  const activate = () => citationDeepLink(citation, file ?? citation.file);
  const detail = `${file ?? citation.file ? `${file ?? citation.file} · ` : ""}${citation.verified ? "Symbol-snapped range" : "Unverified range (no symbol overlap)"} · click to deep-link`;
  return (
    <span
      role="button"
      tabIndex={0}
      className={`studio-cite-chip ${citation.verified ? "studio-cite-chip-verified" : "studio-cite-chip-unverified"}`}
      title={detail}
      onClick={(event) => {
        event.stopPropagation();
        activate();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.stopPropagation();
        event.preventDefault();
        activate();
      }}
    >
      {citation.label}
    </span>
  );
}
