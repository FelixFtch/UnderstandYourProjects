import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type PrivacyLayer = "vault" | "trusted" | "shareable";
export type ConversationKind = "jarvis" | "direct" | "group";
export interface PrivacyItem {
  id: string;
  title: string;
  description: string;
  project: string;
  source: string;
  kind: string;
  layer: PrivacyLayer;
}
export interface SharingDraft { added: string[]; excluded: string[] }

/** Pure selection helper: defaults describe the conversation kind, overrides are local only. */
export function resolveSharingItems(items: PrivacyItem[], defaults: PrivacyLayer[], draft: SharingDraft): PrivacyItem[] {
  const selected = new Set(items.filter((item) => defaults.includes(item.layer)).map((item) => item.id));
  draft.added.forEach((id) => { if (items.some((item) => item.id === id)) selected.add(id); });
  draft.excluded.forEach((id) => selected.delete(id));
  return items.filter((item) => selected.has(item.id));
}

export const privacyLayers: Array<{ id: PrivacyLayer; label: string; short: string; description: string }> = [
  { id: "vault", label: "Private vault", short: "Vault", description: "Sensitive working material. Keep out of conversation defaults." },
  { id: "trusted", label: "Trusted circle", short: "Trusted", description: "Work you may choose to discuss with collaborators." },
  { id: "shareable", label: "Ready to share", short: "Shareable", description: "Material prepared for a wider conversation. Still requires a grant." },
];

// Deliberately gated design fixtures, never a representation of connected user data.
const demoItems: PrivacyItem[] = [
  { id: "research-notes", title: "Unpublished research notes", description: "Working hypotheses, experiments, and observations before publication.", project: "Research Notebook", source: "MacBook · Documents", kind: "Document", layer: "vault" },
  { id: "customer-interviews", title: "Customer interview synthesis", description: "Internal product feedback and interview summaries.", project: "UnderstandYourProjects", source: "NAS · Product research", kind: "Research notes", layer: "vault" },
  { id: "auth-module", title: "Identity service implementation", description: "Source files describing identity resolution and device ownership.", project: "Jarvis HomeHub", source: "GitHub · Private repository", kind: "Source code", layer: "vault" },
  { id: "architecture", title: "Agent Box architecture", description: "How discovery, indexing, retrieval, and evidence fit together.", project: "UnderstandYourProjects", source: "GitHub · docs/architecture", kind: "Architecture document", layer: "trusted" },
  { id: "benchmark", title: "Jetson model benchmark", description: "Draft latency and memory measurements with test conditions.", project: "Jetson Experiments", source: "Jetson · Benchmark reports", kind: "Benchmark report", layer: "trusted" },
  { id: "indexer-code", title: "Incremental indexer module", description: "Reusable code for scanning changes and scheduling project analysis.", project: "UnderstandYourProjects", source: "GitHub · services/indexer", kind: "Source code", layer: "trusted" },
  { id: "project-intro", title: "Project introduction", description: "A concise description of the Agent Box and its intended users.", project: "UnderstandYourProjects", source: "GitHub · README", kind: "Project summary", layer: "shareable" },
  { id: "connector-example", title: "Connector example", description: "A small example showing how an authorized source is discovered.", project: "Connector SDK", source: "GitHub · examples", kind: "Source code", layer: "shareable" },
  { id: "onboarding", title: "Contributor onboarding guide", description: "Project vocabulary, repository navigation, and a first contribution path.", project: "UnderstandYourProjects", source: "NAS · Team handbook", kind: "Document", layer: "shareable" },
];

const emptyDraft = (): SharingDraft => ({ added: [], excluded: [] });

interface PrivacyWorkspaceState {
  items: PrivacyItem[];
  isDemo: boolean;
  defaultLayers: PrivacyLayer[];
  setDefaultLayers: (layers: PrivacyLayer[]) => void;
  setItemLayer: (itemId: string, layer: PrivacyLayer) => void;
  draftFor: (id: string) => SharingDraft;
  effectiveItems: (id: string, kind: ConversationKind) => PrivacyItem[];
  inheritedItems: (kind: ConversationKind) => PrivacyItem[];
  addItem: (id: string, itemId: string) => void;
  excludeItem: (id: string, itemId: string) => void;
  removeAddedItem: (id: string, itemId: string) => void;
  restoreItem: (id: string, itemId: string) => void;
  resetDraft: (id: string) => void;
}

const PrivacyContext = createContext<PrivacyWorkspaceState | null>(null);

export function PrivacyWorkspaceProvider({ children }: { children: ReactNode }) {
  const isDemo = import.meta.env.VITE_DEMO_MODE === "true";
  const [items, setItems] = useState<PrivacyItem[]>(() => isDemo ? demoItems.map((item) => ({ ...item })) : []);
  const [defaultLayers, updateDefaultLayers] = useState<PrivacyLayer[]>(["shareable"]);
  const [drafts, setDrafts] = useState<Record<string, SharingDraft>>({});
  const value = useMemo<PrivacyWorkspaceState>(() => {
    const validIds = new Set(items.map((item) => item.id));
    const draftFor = (id: string) => {
      const draft = drafts[id] ?? emptyDraft();
      return { added: draft.added.filter((itemId) => validIds.has(itemId)), excluded: draft.excluded.filter((itemId) => validIds.has(itemId)) };
    };
    const inheritedItems = (kind: ConversationKind) => kind === "jarvis" ? items : items.filter((item) => defaultLayers.includes(item.layer));
    const changeDraft = (id: string, update: (draft: SharingDraft) => SharingDraft) => setDrafts((current) => ({ ...current, [id]: update(current[id] ?? emptyDraft()) }));
    return {
      items,
      isDemo,
      defaultLayers,
      setDefaultLayers: (layers) => updateDefaultLayers([...new Set(layers.filter((layer) => privacyLayers.some((option) => option.id === layer)))]),
      setItemLayer: (itemId, layer) => {
        if (!privacyLayers.some((option) => option.id === layer)) return;
        setItems((current) => current.map((item) => item.id === itemId ? { ...item, layer } : item));
      },
      draftFor,
      inheritedItems,
      effectiveItems: (id, kind) => {
        const draft = draftFor(id);
        const selected = new Set([...inheritedItems(kind).map((item) => item.id), ...draft.added]);
        return items.filter((item) => selected.has(item.id) && !draft.excluded.includes(item.id));
      },
      addItem: (id, itemId) => {
        if (!validIds.has(itemId)) return;
        changeDraft(id, (draft) => ({ added: [...new Set([...draft.added, itemId])], excluded: draft.excluded.filter((key) => key !== itemId) }));
      },
      excludeItem: (id, itemId) => {
        if (!validIds.has(itemId)) return;
        changeDraft(id, (draft) => ({ added: draft.added.filter((key) => key !== itemId), excluded: [...new Set([...draft.excluded, itemId])] }));
      },
      removeAddedItem: (id, itemId) => changeDraft(id, (draft) => ({ ...draft, added: draft.added.filter((key) => key !== itemId) })),
      restoreItem: (id, itemId) => changeDraft(id, (draft) => ({ ...draft, excluded: draft.excluded.filter((key) => key !== itemId) })),
      resetDraft: (id) => setDrafts((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      }),
    };
  }, [items, defaultLayers, drafts, isDemo]);
  return <PrivacyContext.Provider value={value}>{children}</PrivacyContext.Provider>;
}

export function usePrivacyWorkspace() {
  const context = useContext(PrivacyContext);
  if (!context) throw new Error("Privacy workspace must be rendered inside PrivacyWorkspaceProvider.");
  return context;
}
