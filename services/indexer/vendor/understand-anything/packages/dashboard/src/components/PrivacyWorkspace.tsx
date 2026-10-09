import { useMemo, useState } from "react";
import type { DragEvent } from "react";
import type { ConversationKind, PrivacyItem, PrivacyLayer } from "./privacy-model";
import { privacyLayers, usePrivacyWorkspace } from "./privacy-model";
import "./privacy-workspace.css";

const layerColor: Record<PrivacyLayer, string> = { vault: "#7D6426", trusted: "#C49A2E", shareable: "#F2D24B" };

function LayerGlyph({ layer }: { layer: PrivacyLayer }) {
  return <span className="pv-layer-glyph" style={{ background: layerColor[layer] }} aria-hidden="true" />;
}

function KindIcon({ kind }: { kind: string }) {
  const icon = kind.toLowerCase().includes("code") ? "⌘" : kind.toLowerCase().includes("report") ? "◒" : "▤";
  return <span className="pv-kind-icon" aria-hidden="true">{icon}</span>;
}

function ItemMeta({ item }: { item: PrivacyItem }) {
  return <span className="pv-item-meta">{item.kind} · {item.source}</span>;
}

function ringLayerForPoint(event: { clientX: number; clientY: number }, element: HTMLElement): PrivacyLayer {
  const bounds = element.getBoundingClientRect();
  const dx = event.clientX - (bounds.left + bounds.width / 2);
  const dy = event.clientY - (bounds.top + bounds.height / 2);
  const radius = Math.sqrt(dx * dx + dy * dy) / (Math.min(bounds.width, bounds.height) / 2);
  if (radius < 0.48) return "vault";
  if (radius < 0.72) return "trusted";
  return "shareable";
}

export default function PrivacyWorkspace({ onOpenConversations }: { onOpenConversations: () => void }) {
  const { items, isDemo, defaultLayers, setDefaultLayers, setItemLayer } = usePrivacyWorkspace();
  const [selectedLayer, setSelectedLayer] = useState<PrivacyLayer | "all">("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragOverLayer, setDragOverLayer] = useState<PrivacyLayer | null>(null);
  const filtered = useMemo(() => items.filter((item) => {
    const text = `${item.title} ${item.description} ${item.project} ${item.source} ${item.kind}`.toLowerCase();
    return (selectedLayer === "all" || item.layer === selectedLayer) && (!query.trim() || text.includes(query.trim().toLowerCase()));
  }), [items, query, selectedLayer]);
  const toggleDefault = (layer: PrivacyLayer) => setDefaultLayers(defaultLayers.includes(layer) ? defaultLayers.filter((value) => value !== layer) : [...defaultLayers, layer]);
  const count = (layer: PrivacyLayer) => items.filter((item) => item.layer === layer).length;
  const handleRingDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const ring = event.currentTarget as HTMLElement;
    setDragOverLayer(ringLayerForPoint(event, ring));
  };
  const handleRingDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const ring = event.currentTarget as HTMLElement;
    const itemId = event.dataTransfer.getData("text/plain");
    const item = items.find((candidate) => candidate.id === itemId);
    if (item) setItemLayer(item.id, ringLayerForPoint(event, ring));
    setDragOverLayer(null);
  };
  const handleRingDragLeave = (event: DragEvent<HTMLDivElement>) => {
    const related = event.relatedTarget as Node | null;
    if (!related || !event.currentTarget.contains(related)) setDragOverLayer(null);
  };

  return <section className="pv-workspace" aria-label="Privacy workspace">
    <div className="pv-workspace-header">
      <div>
        <p className="pv-eyebrow">YOUR DATA MAP</p>
        <h1>Privacy layers</h1>
        <p className="pv-lede">Decide what Jarvis can discuss by default. A conversation can add or remove individual items without changing your global map.</p>
      </div>
      <button className="pv-secondary-button" onClick={onOpenConversations}>Open conversations <span aria-hidden="true">↗</span></button>
    </div>
    {isDemo && <div className="pv-demo-notice" role="status"><span className="pv-demo-dot" /> Demo inventory · local draft only · HomeHub has not issued a permission</div>}
    <div className="pv-workspace-grid">
      <section className="pv-ring-panel" aria-labelledby="privacy-map-title">
        <div className="pv-panel-heading"><div><h2 id="privacy-map-title">Your privacy map</h2><p>Drag an item onto a ring to change its layer</p></div><span className="pv-count-label">{items.length} items</span></div>
        <div className="pv-ring-stage">
          <div className={`pv-ring ${dragOverLayer ? `is-drop-${dragOverLayer}` : ""}`} onDragOver={handleRingDragOver} onDrop={handleRingDrop} onDragLeave={handleRingDragLeave} aria-label="Privacy layers drop target">
            <div className="pv-ring-core" aria-hidden="true"><strong>{items.length}</strong><span>{dragOverLayer ? `Drop in ${privacyLayers.find((layer) => layer.id === dragOverLayer)?.short}` : "indexed items"}</span></div>
          </div>
          <button className="pv-ring-label pv-ring-label-vault" onClick={() => setSelectedLayer("vault")} aria-label={`Show private vault items, ${count("vault")} items`}><LayerGlyph layer="vault" /><span><strong>{count("vault")}</strong> private</span></button>
          <button className="pv-ring-label pv-ring-label-trusted" onClick={() => setSelectedLayer("trusted")} aria-label={`Show trusted circle items, ${count("trusted")} items`}><LayerGlyph layer="trusted" /><span><strong>{count("trusted")}</strong> trusted</span></button>
          <button className="pv-ring-label pv-ring-label-shareable" onClick={() => setSelectedLayer("shareable")} aria-label={`Show shareable items, ${count("shareable")} items`}><LayerGlyph layer="shareable" /><span><strong>{count("shareable")}</strong> shareable</span></button>
        </div>
        <div className="pv-layer-trays" aria-label="Privacy layer item trays">{privacyLayers.map((layer) => <section className={`pv-layer-tray pv-layer-tray-${layer.id}`} key={layer.id} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }} onDrop={(event) => { event.preventDefault(); const itemId = event.dataTransfer.getData("text/plain"); if (items.some((item) => item.id === itemId)) setItemLayer(itemId, layer.id); }}><div className="pv-layer-tray-heading"><div><LayerGlyph layer={layer.id} /><strong>{layer.label}</strong></div><span>{count(layer.id)} items</span></div><p>{layer.description}</p><div className="pv-layer-tray-items">{items.filter((item) => item.layer === layer.id).map((item) => <button type="button" draggable key={item.id} className={`pv-layer-item ${selectedId === item.id ? "is-selected" : ""}`} onClick={() => setSelectedId(selectedId === item.id ? null : item.id)} onDragStart={(event) => { event.dataTransfer.setData("text/plain", item.id); event.dataTransfer.effectAllowed = "move"; setSelectedId(item.id); }} onDragEnd={() => setDragOverLayer(null)}><KindIcon kind={item.kind} /><span><strong>{item.title}</strong><small>{item.kind} · {item.source}</small></span><span className="pv-drag-mark" aria-hidden="true">⠿</span></button>)}</div></section>)}</div>
        {selectedId && items.find((item) => item.id === selectedId) && <div className="pv-ring-selection"><div className="pv-ring-selection-title"><span className="pv-section-kicker">SELECTED ITEM</span><button type="button" onClick={() => setSelectedId(null)} aria-label="Close selected item">×</button></div><strong>{items.find((item) => item.id === selectedId)?.title}</strong><p>{items.find((item) => item.id === selectedId)?.description}</p><span><b>Project</b> {items.find((item) => item.id === selectedId)?.project} · <b>Source</b> {items.find((item) => item.id === selectedId)?.source}</span></div>}
        <div className="pv-layer-filters" role="toolbar" aria-label="Filter privacy layers">
          <button className={selectedLayer === "all" ? "is-active" : ""} onClick={() => setSelectedLayer("all")}><span className="pv-filter-dot pv-filter-all" />All <b>{items.length}</b></button>
          {privacyLayers.map((layer) => <button key={layer.id} className={selectedLayer === layer.id ? "is-active" : ""} onClick={() => setSelectedLayer(layer.id)}><span className="pv-filter-dot" style={{ background: layerColor[layer.id] }} />{layer.short} <b>{count(layer.id)}</b></button>)}
        </div>
        <div className="pv-defaults">
          <div className="pv-defaults-heading"><div><h3>Default conversation sharing</h3><p>Applies to new direct chats and groups</p></div><span className="pv-draft-pill">Draft</span></div>
          <div className="pv-default-layer-list">{privacyLayers.map((layer) => <button key={layer.id} className={`pv-default-layer ${defaultLayers.includes(layer.id) ? "is-enabled" : ""}`} onClick={() => toggleDefault(layer.id)} aria-pressed={defaultLayers.includes(layer.id)}><LayerGlyph layer={layer.id} /><span>{layer.label}</span><span className="pv-toggle" aria-hidden="true">{defaultLayers.includes(layer.id) ? "On" : "Off"}</span></button>)}</div>
          <div className="pv-defaults-flow"><span>New direct chat or group</span><b>inherits</b><span>selected layer defaults</span></div>
          <p className="pv-default-note"><span aria-hidden="true">↗</span> Jarvis and HomeHub still verify access before anything is shared.</p>
        </div>
      </section>
      <section className="pv-inventory-panel" aria-labelledby="privacy-inventory-title">
        <div className="pv-panel-heading"><div><h2 id="privacy-inventory-title">Layer inventory</h2><p>Every item keeps its source and project context</p></div><span className="pv-edit-label">Local classification</span></div>
        <label className="pv-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search projects, files, or sources" aria-label="Search privacy inventory" /></label>
        <div className="pv-inventory-list">{filtered.map((item) => <article className={`pv-inventory-item ${selectedId === item.id ? "is-selected" : ""}`} key={item.id} draggable onDragStart={(event) => { event.dataTransfer.setData("text/plain", item.id); event.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => setDragOverLayer(null)} onClick={() => setSelectedId(selectedId === item.id ? null : item.id)}>
          <KindIcon kind={item.kind} /><div className="pv-item-copy"><div className="pv-item-title"><strong>{item.title}</strong><span className="pv-item-layer"><LayerGlyph layer={item.layer} />{privacyLayers.find((layer) => layer.id === item.layer)?.short}</span></div><ItemMeta item={item} /><p>{item.description}</p>{selectedId === item.id && <div className="pv-item-detail"><span><b>Project</b>{item.project}</span><span><b>Source</b>{item.source}</span></div>}</div>
          <select className="pv-layer-select" value={item.layer} onChange={(event) => { event.stopPropagation(); setItemLayer(item.id, event.target.value as PrivacyLayer); }} onClick={(event) => event.stopPropagation()} aria-label={`Classify ${item.title}`}><option value="vault">Private vault</option><option value="trusted">Trusted circle</option><option value="shareable">Ready to share</option></select>
        </article>)}
        {!filtered.length && <div className="pv-empty"><span aria-hidden="true">⌕</span><strong>{items.length ? "No matching items" : "No connected inventory yet"}</strong><p>{items.length ? "Try a different project, source, or layer." : "Connect a source to build your privacy map. Nothing is inferred here."}</p></div>}
        </div>
      </section>
    </div>
  </section>;
}

export function SharingScopePanel({ conversationId, kind, recipientLabel, onOpenPrivacy }: { conversationId: string; kind: ConversationKind; recipientLabel: string; onOpenPrivacy: () => void }) {
  const { items, isDemo, draftFor, inheritedItems, effectiveItems, addItem, excludeItem, removeAddedItem, restoreItem, resetDraft } = usePrivacyWorkspace();
  const [showAll, setShowAll] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const draft = draftFor(conversationId);
  const inherited = inheritedItems(kind);
  const effective = effectiveItems(conversationId, kind);
  const visible = showAll ? effective : effective.slice(0, 4);
  const excludedItems = items.filter((item) => draft.excluded.includes(item.id));
  const candidates = items.filter((item) => !effective.some((selected) => selected.id === item.id) && `${item.title} ${item.project} ${item.source}`.toLowerCase().includes(query.toLowerCase()));
  const kindLabel = kind === "jarvis" ? "Private Jarvis" : kind === "group" ? "Group default" : "Direct chat default";
  return <aside className="pv-scope-panel" aria-label={`Sharing scope for ${recipientLabel}`}>
    <div className="pv-scope-header"><div><p className="pv-eyebrow">SHARING SCOPE</p><h2>{recipientLabel}</h2></div><span className="pv-draft-pill">Draft only</span></div>
    {isDemo && <div className="pv-scope-demo"><span className="pv-demo-dot" /> Demo policy preview · no permission issued</div>}
    <div className="pv-scope-baseline"><span className="pv-lock-mark" aria-hidden="true">⌁</span><div><strong>{kindLabel}</strong><p>{kind === "jarvis" ? "All locally authorized items" : "Ready to share layer"} · {inherited.length} inherited</p></div><button onClick={onOpenPrivacy}>Manage map</button></div>
    <div className="pv-scope-summary"><div className="pv-scope-summary-stats"><span><b>{effective.length}</b> included</span><span><b>{draft.added.length}</b> added</span><span><b>{draft.excluded.length}</b> hidden</span></div><div className="pv-scope-summary-items">{effective.slice(0, 2).map((item) => <span key={item.id}>{item.title}</span>)}{effective.length > 2 && <span>+{effective.length - 2} more</span>}{!effective.length && <span>Nothing selected yet</span>}</div><button type="button" className="pv-scope-edit-toggle" onClick={() => setEditorOpen(!editorOpen)} aria-expanded={editorOpen}><span aria-hidden="true">{editorOpen ? "⌃" : "⌄"}</span>{editorOpen ? "Close scope editor" : "Edit scope"}</button></div>
    {editorOpen && <div className="pv-scope-editor"><div className="pv-scope-section-heading"><div><h3>Conversation can see</h3><p>Inherited defaults plus per-conversation overrides</p></div>{effective.length > 4 && <button className="pv-link-button" onClick={() => setShowAll(!showAll)}>{showAll ? "Show less" : `View all ${effective.length}`}</button>}</div>
      <div className="pv-scope-items">{visible.map((item) => { const added = draft.added.includes(item.id); return <div className="pv-scope-item" key={item.id}><KindIcon kind={item.kind} /><div><strong>{item.title}</strong><ItemMeta item={item} /></div><span className={`pv-item-origin ${added ? "is-added" : ""}`}>{added ? "Added" : "Default"}</span><button className="pv-icon-button" onClick={() => added ? removeAddedItem(conversationId, item.id) : excludeItem(conversationId, item.id)} aria-label={`${added ? "Remove added" : "Hide default"} ${item.title}`}>×</button></div>; })}</div>
      {!effective.length && <div className="pv-scope-empty">Nothing is selected for this conversation. Add a specific item below.</div>}
      <button className="pv-add-button" onClick={() => setPickerOpen(!pickerOpen)} aria-expanded={pickerOpen}><span aria-hidden="true">＋</span> Add specific item</button>
      {pickerOpen && <div className="pv-picker"><label className="pv-search pv-search-small"><span aria-hidden="true">⌕</span><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find an item to add" aria-label="Find item to add" /></label>{candidates.slice(0, 6).map((item) => <button className="pv-picker-item" key={item.id} onClick={() => { addItem(conversationId, item.id); setQuery(""); }}><KindIcon kind={item.kind} /><span><strong>{item.title}</strong><small>{item.project} · {item.source}</small></span><span aria-hidden="true">＋</span></button>)}{!candidates.length && <p className="pv-picker-empty">No other inventory item matches.</p>}</div>}
      {excludedItems.length > 0 && <div className="pv-excluded"><div className="pv-scope-section-heading"><div><h3>Hidden for this conversation</h3><p>Removed from inherited defaults</p></div></div>{excludedItems.map((item) => <div className="pv-excluded-item" key={item.id}><span>{item.title}</span><button onClick={() => restoreItem(conversationId, item.id)}>Restore</button></div>)}</div>}
    </div>}
    <div className="pv-scope-footer"><button className="pv-reset-button" onClick={() => resetDraft(conversationId)}>Reset to default</button><span>HomeHub reviews any real grant</span></div>
  </aside>;
}
