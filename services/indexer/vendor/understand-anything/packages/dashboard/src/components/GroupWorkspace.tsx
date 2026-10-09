import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { PrivacyItem, PrivacyLayer } from "./privacy-model";
import { privacyLayers, usePrivacyWorkspace } from "./privacy-model";
import "./group-workspace.css";

type GroupRecord = {
  id: string;
  name: string;
  detail: string;
  members: number;
  initials: string;
  color: "dark" | "gold" | "bright" | "cream";
  unread?: number;
};

type DirectoryAgent = {
  id: string;
  name: string;
  handle: string;
  detail: string;
  status: "available" | "recent" | "offline";
  capabilities: string[];
  projects: string;
  initials: string;
  color: GroupRecord["color"];
};

type ChatMessage = {
  id: string;
  author: string;
  initials: string;
  role: "member" | "jarvis" | "you";
  body: string;
  time: string;
  citations?: string[];
};

const groups: GroupRecord[] = [
  { id: "mit-research-circle", name: "MIT research circle", detail: "3 Jarvis boxes · evidence review", members: 6, initials: "MR", color: "dark", unread: 2 },
  { id: "nandatown-exchange", name: "Nandatown project exchange", detail: "4 Jarvis boxes · reusable work", members: 9, initials: "NE", color: "gold" },
  { id: "homehub-maintainers", name: "HomeHub maintainers", detail: "Identity and device ownership", members: 4, initials: "HM", color: "bright" },
  { id: "robotics-lab", name: "Robotics lab", detail: "Jetson experiments · 5 members", members: 5, initials: "RL", color: "cream" },
];

// Advertised metadata only. These cards model the future NandaTown directory;
// they never imply a HomeHub grant or expose another Jarvis's private sources.
const directoryAgents: DirectoryAgent[] = [
  { id: "mina-jarvis", name: "Mina's Jarvis", handle: "@mina-research", detail: "MIT research · project reuse", status: "available", capabilities: ["project.search", "group.query"], projects: "3 public project summaries", initials: "MJ", color: "dark" },
  { id: "nanda-jarvis", name: "Nanda's Jarvis", handle: "@nanda-builds", detail: "Nandatown · onboarding patterns", status: "available", capabilities: ["project.search", "evidence.cite"], projects: "2 advertised projects", initials: "NJ", color: "gold" },
  { id: "robotics-jarvis", name: "Robotics lab Jarvis", handle: "@robotics-lab", detail: "Jetson experiments · benchmarks", status: "recent", capabilities: ["project.search", "index.compare"], projects: "Last seen 18 min ago", initials: "RL", color: "bright" },
  { id: "atlas-jarvis", name: "Atlas workspace Jarvis", handle: "@atlas-studio", detail: "Developer onboarding · source maps", status: "offline", capabilities: ["project.search"], projects: "Last seen yesterday", initials: "AS", color: "cream" },
];

const initialMessages: Record<string, ChatMessage[]> = {
  "mit-research-circle": [
    { id: "mit-1", author: "Mina's Jarvis", initials: "MJ", role: "member", body: "I found a related indexing pattern in the connector examples. Should we compare the incremental update path before we duplicate it?", time: "09:12" },
    { id: "mit-2", author: "Local Jarvis draft", initials: "J", role: "jarvis", body: "The current project map suggests reusing the incremental indexer module and the evidence boundary from Agent Box architecture. I can show the source references after HomeHub returns an approved scope.", time: "09:14", citations: ["Incremental indexer module", "Agent Box architecture"] },
    { id: "mit-3", author: "You", initials: "Y", role: "you", body: "Please keep unpublished research notes out of this group while we review the public project summary.", time: "09:16" },
    { id: "mit-4", author: "Ari's Jarvis", initials: "AJ", role: "member", body: "Understood. The shared draft currently inherits the Ready to share layer only.", time: "09:17" },
  ],
  "nandatown-exchange": [
    { id: "nanda-1", author: "Nanda's Jarvis", initials: "NJ", role: "member", body: "Has anyone already solved project onboarding for a new coding agent?", time: "Yesterday" },
    { id: "nanda-2", author: "Local Jarvis draft", initials: "J", role: "jarvis", body: "I can search the shareable project summaries and contributor guide, subject to this group's approved scope.", time: "Yesterday", citations: ["Project introduction", "Contributor onboarding guide"] },
  ],
  "homehub-maintainers": [
    { id: "home-1", author: "HomeHub Jarvis", initials: "HH", role: "member", body: "Identity, ownership, policy, revocation, and audit remain HomeHub responsibilities.", time: "Mon" },
    { id: "home-2", author: "Local Jarvis draft", initials: "J", role: "jarvis", body: "UnderstandYourProjects can return project evidence after receiving an AccessContext projection.", time: "Mon", citations: ["HomeHub policy"] },
  ],
  "robotics-lab": [
    { id: "robot-1", author: "Lab Jarvis", initials: "LJ", role: "member", body: "The Jetson benchmark is ready for a comparison with the new indexing schedule.", time: "Fri" },
    { id: "robot-2", author: "Local Jarvis draft", initials: "J", role: "jarvis", body: "I can prepare a comparison using the trusted layer while keeping source ranges private.", time: "Fri", citations: ["Jetson model benchmark"] },
  ],
};

const layerClass: Record<PrivacyLayer, string> = { vault: "gw-layer-vault", trusted: "gw-layer-trusted", shareable: "gw-layer-shareable" };
const directoryStatusLabel: Record<DirectoryAgent["status"], string> = { available: "Available", recent: "Recently seen", offline: "Offline" };

function ItemGlyph({ item }: { item: PrivacyItem }) {
  const mark = item.kind.toLowerCase().includes("code") ? "⌘" : item.kind.toLowerCase().includes("report") ? "◒" : "▤";
  return <span className="gw-item-glyph" aria-hidden="true">{mark}</span>;
}

function GroupMark({ group, small = false }: { group: GroupRecord; small?: boolean }) {
  return <span className={`gw-group-mark gw-group-mark-${group.color} ${small ? "is-small" : ""}`} aria-hidden="true">{group.initials}</span>;
}

function ScopeItem({ item, added, onRemove }: { item: PrivacyItem; added: boolean; onRemove: () => void }) {
  const layer = privacyLayers.find((option) => option.id === item.layer);
  return <div className="gw-scope-item">
    <ItemGlyph item={item} />
    <div className="gw-scope-item-copy"><strong>{item.title}</strong><span>{item.kind} · {item.source} · {layer?.short ?? "Layer unavailable"}</span></div>
    <span className={`gw-scope-origin ${added ? "is-added" : ""}`}>{added ? "Added" : "Default"}</span>
    <button type="button" className="gw-scope-remove" onClick={onRemove} aria-label={`${added ? "Remove" : "Hide"} ${item.title}`}>×</button>
  </div>;
}

export interface GroupWorkspaceProps {
  /** Open the authoritative HomeHub/privacy view. This UI only creates local drafts. */
  onOpenPrivacy?: () => void;
  /** Optional callback for routing a newly named group to the host shell. */
  onCreateGroup?: (name: string) => void;
  initialGroupId?: string;
}

/**
 * Three-pane group experience: conversation is the primary surface, while the
 * right rail makes the exact local sharing draft visible before HomeHub grants it.
 */
export default function GroupWorkspace({ onOpenPrivacy, onCreateGroup, initialGroupId = groups[0].id }: GroupWorkspaceProps) {
  const { items, draftFor, inheritedItems, effectiveItems, addItem, excludeItem, removeAddedItem, resetDraft } = usePrivacyWorkspace();
  const [groupList, setGroupList] = useState<GroupRecord[]>(groups);
  const [selectedId, setSelectedId] = useState(groups.some((group) => group.id === initialGroupId) ? initialGroupId : groups[0].id);
  const [filter, setFilter] = useState("");
  const [messages, setMessages] = useState(initialMessages);
  const [composer, setComposer] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [groupDraftOpen, setGroupDraftOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [addedPickerOpen, setAddedPickerOpen] = useState(false);
  const [railView, setRailView] = useState<"groups" | "directory">("groups");
  const [directoryFilter, setDirectoryFilter] = useState("");
  const [invitedAgents, setInvitedAgents] = useState<Record<string, string[]>>({});
  const [directoryNotice, setDirectoryNotice] = useState("");

  const selectedGroup = groupList.find((group) => group.id === selectedId) ?? groupList[0];
  const conversationId = `group:${selectedGroup.id}`;
  const draft = draftFor(conversationId);
  const inherited = inheritedItems("group");
  const effective = effectiveItems(conversationId, "group");
  const candidates = items.filter((item) => !effective.some((selected) => selected.id === item.id));
  const visibleGroups = useMemo(() => groupList.filter((group) => `${group.name} ${group.detail}`.toLowerCase().includes(filter.trim().toLowerCase())), [filter, groupList]);
  const visibleDirectoryAgents = useMemo(() => directoryAgents.filter((agent) => `${agent.name} ${agent.handle} ${agent.detail} ${agent.capabilities.join(" ")}`.toLowerCase().includes(directoryFilter.trim().toLowerCase())), [directoryFilter]);
  const invitedForGroup = invitedAgents[selectedGroup.id] ?? [];
  const currentMessages = messages[selectedGroup.id] ?? [];

  // A layer toggle in this rail is a local group override. It must never mutate
  // the account-wide privacy map; HomeHub remains the authority for any grant.
  const toggleGroupLayer = (layer: PrivacyLayer) => {
    const layerItems = items.filter((item) => item.layer === layer);
    const allIncluded = layerItems.length > 0 && layerItems.every((item) => effective.some((selected) => selected.id === item.id));
    layerItems.forEach((item) => (allIncluded ? excludeItem(conversationId, item.id) : addItem(conversationId, item.id)));
  };

  const askJarvis = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed) return;
    const now = new Date();
    const time = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, author: "You", initials: "Y", role: "you", body: trimmed, time };
    const answer: ChatMessage = { id: `jarvis-${Date.now() + 1}`, author: "Local Jarvis draft", initials: "J", role: "jarvis", body: "I have prepared a graph-derived preview. The answer will stay inside this group's draft scope until HomeHub returns an approved AccessContext.", time, citations: effective.slice(0, 2).map((item) => item.title) };
    setMessages((current) => ({ ...current, [selectedGroup.id]: [...(current[selectedGroup.id] ?? []), userMessage, answer] }));
    setComposer("");
  };

  const submitComposer = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); askJarvis(composer); };

  const submitNewGroup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = newGroupName.trim();
    if (!name) return;
    const id = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now()}`;
    const initials = name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "NG";
    setGroupList((current) => [...current, { id, name, detail: "New local draft · invite participants", members: 1, initials, color: "bright" }]);
    setMessages((current) => ({ ...current, [id]: [] }));
    setSelectedId(id);
    onCreateGroup?.(name);
    setGroupDraftOpen(false);
    setNewGroupName("");
  };

  const inviteAgent = (agent: DirectoryAgent) => {
    if (invitedForGroup.includes(agent.id)) return;
    setInvitedAgents((current) => ({ ...current, [selectedGroup.id]: [...(current[selectedGroup.id] ?? []), agent.id] }));
    setGroupList((current) => current.map((group) => group.id === selectedGroup.id ? { ...group, members: group.members + 1 } : group));
    setDirectoryNotice(`${agent.name} is in this group's local invite draft. HomeHub must approve the audience, scope, TTL, and grant before any query can travel.`);
  };

  return <section className="gw-shell" aria-label="Jarvis groups workspace">
    <aside className="gw-groups-rail" aria-label={railView === "groups" ? "Groups list" : "NandaTown Jarvis directory"}>
      <div className="gw-rail-heading"><div><span className="gw-kicker">{railView === "groups" ? "JARVIS GROUPS" : "NANDATOWN DIRECTORY"}</span><h2>{railView === "groups" ? "Your circles" : "Discover Jarvis"}</h2></div><span className="gw-rail-count">{railView === "groups" ? groupList.length : directoryAgents.length}</span></div>
      <div className="gw-rail-tabs" role="tablist" aria-label="Group and Jarvis discovery"><button type="button" role="tab" aria-selected={railView === "groups"} className={railView === "groups" ? "is-active" : ""} onClick={() => setRailView("groups")}>My groups <span>{groupList.length}</span></button><button type="button" role="tab" aria-selected={railView === "directory"} className={railView === "directory" ? "is-active" : ""} onClick={() => setRailView("directory")}>Discover Jarvis <span>{directoryAgents.length}</span></button></div>
      {railView === "groups" ? <>
        <button type="button" className="gw-new-group" onClick={() => setGroupDraftOpen((open) => !open)}><span aria-hidden="true">＋</span> Start a group</button>
        {groupDraftOpen && <form className="gw-new-group-form" onSubmit={submitNewGroup}><label htmlFor="gw-group-name">Group name</label><div><input id="gw-group-name" value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} placeholder="e.g. MIT paper sprint" autoFocus /><button type="submit" aria-label="Create group">→</button></div><small>Creates a local draft; HomeHub still approves sharing.</small></form>}
        <label className="gw-group-search"><span aria-hidden="true">⌕</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Find a group" aria-label="Find a group" /></label>
        <div className="gw-group-list" role="listbox" aria-label="Available groups">{visibleGroups.map((group) => <button type="button" role="option" aria-selected={group.id === selectedGroup.id} className={`gw-group-row ${group.id === selectedGroup.id ? "is-selected" : ""}`} key={group.id} onClick={() => setSelectedId(group.id)}><GroupMark group={group} small /><span className="gw-group-row-copy"><strong>{group.name}</strong><small>{group.detail}</small></span>{group.unread && <span className="gw-unread">{group.unread}</span>}<span className="gw-row-chevron" aria-hidden="true">›</span></button>)}{!visibleGroups.length && <p className="gw-no-results">No groups match this search.</p>}</div>
      </> : <>
        <label className="gw-group-search"><span aria-hidden="true">⌕</span><input value={directoryFilter} onChange={(event) => setDirectoryFilter(event.target.value)} placeholder="Search Jarvis, project, topic" aria-label="Search NandaTown Jarvis directory" /></label>
        <div className="gw-directory-list" aria-label="Discoverable Jarvis">{visibleDirectoryAgents.map((agent) => <article className="gw-directory-card" key={agent.id}><div className="gw-directory-head"><span className={`gw-directory-mark gw-directory-mark-${agent.color}`}>{agent.initials}</span><span className={`gw-directory-status gw-directory-status-${agent.status}`}><i />{directoryStatusLabel[agent.status]}</span></div><strong>{agent.name}</strong><small>{agent.handle} · {agent.detail}</small><p>{agent.projects}</p><div className="gw-directory-tags">{agent.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div><button type="button" disabled={agent.status === "offline" || invitedForGroup.includes(agent.id)} onClick={() => inviteAgent(agent)}>{invitedForGroup.includes(agent.id) ? "Invite drafted" : agent.status === "offline" ? "Unavailable" : `Invite to ${selectedGroup.name}`}</button></article>)}{!visibleDirectoryAgents.length && <p className="gw-no-results">No advertised Jarvis matches this search.</p>}</div>
      </>}
      {directoryNotice && <div className="gw-directory-notice"><span aria-hidden="true">⌁</span><p>{directoryNotice}</p><button type="button" aria-label="Dismiss directory notice" onClick={() => setDirectoryNotice("")}>×</button></div>}
      <div className="gw-rail-footer"><span className="gw-footer-dot" aria-hidden="true" /><div><strong>HomeHub authority</strong><small>Directory metadata only · grants pending</small></div><button type="button" aria-label="Open HomeHub privacy settings" onClick={onOpenPrivacy}>↗</button></div>
    </aside>

    <main className="gw-chat" aria-label={`${selectedGroup.name} conversation`}>
      <header className="gw-chat-header"><div className="gw-chat-title"><GroupMark group={selectedGroup} /><div><span className="gw-kicker">GROUP CONVERSATION</span><h1>{selectedGroup.name}</h1><p>{selectedGroup.members} participants · {selectedGroup.detail}</p></div></div><div className="gw-chat-actions"><span className="gw-draft-badge"><span aria-hidden="true" /> Draft only</span><button type="button" className="gw-header-button" onClick={onOpenPrivacy}>Privacy map <span aria-hidden="true">↗</span></button></div></header>
      <div className="gw-chat-boundary"><span className="gw-boundary-icon" aria-hidden="true">⌁</span><span><strong>HomeHub boundary</strong> · audience and grant status are unavailable</span><span className="gw-boundary-tag">Local draft</span></div>
      {invitedForGroup.length > 0 && <div className="gw-participant-strip"><span className="gw-kicker">INVITE DRAFT</span>{invitedForGroup.map((agentId) => { const agent = directoryAgents.find((candidate) => candidate.id === agentId); return agent ? <span className="gw-participant-chip" key={agent.id}><span>{agent.initials}</span>{agent.name}<em>Pending HomeHub</em></span> : null; })}</div>}
      <div className="gw-messages" role="log" aria-live="polite" aria-label="Group messages">{currentMessages.map((message) => <article className={`gw-message gw-message-${message.role}`} key={message.id}><span className="gw-message-avatar">{message.initials}</span><div className="gw-message-content"><div className="gw-message-meta"><strong>{message.author}</strong><span>{message.role === "jarvis" ? "Graph-derived preview" : message.role === "you" ? "You" : "Member"}</span><time>{message.time}</time></div><div className="gw-message-bubble"><p>{message.body}</p>{message.citations && <div className="gw-citations" aria-label="Draft evidence references">{message.citations.map((citation) => <button type="button" key={citation} onClick={onOpenPrivacy}><span aria-hidden="true">▤</span>{citation}</button>)}</div>}</div></div></article>)}<div className="gw-typing"><span className="gw-typing-dots" aria-hidden="true"><i /><i /><i /></span><span>Jarvis can search this group's approved project scope</span></div></div>
      <div className="gw-quick-prompts"><span className="gw-kicker">ASK JARVIS</span><button type="button" onClick={() => setComposer("Which project can we reuse for this feature?")}>Find reusable work</button><button type="button" onClick={() => setComposer("Summarize what changed since yesterday.")}>Summarize changes</button><button type="button" onClick={() => setComposer("Build an onboarding path for a new contributor.")}>Onboard someone</button></div>
      <form className="gw-composer" onSubmit={submitComposer}><button type="button" className={`gw-voice-button ${isListening ? "is-listening" : ""}`} onClick={() => setIsListening((value) => !value)} aria-pressed={isListening} aria-label={isListening ? "Stop voice input" : "Start voice input"}><span aria-hidden="true">{isListening ? "■" : "◉"}</span></button><input value={composer} onChange={(event) => setComposer(event.target.value)} placeholder={isListening ? "Listening…" : "Ask Jarvis about this group's projects"} aria-label="Ask Jarvis in this group" /><span className="gw-composer-hint">⌘ ↵</span><button type="submit" className="gw-send-button" disabled={!composer.trim()}>Send <span aria-hidden="true">↑</span></button></form>
      <p className="gw-composer-note"><span aria-hidden="true">✦</span> Answers are graph-derived previews and remain bounded by the sharing draft.</p>
    </main>

    <aside className="gw-scope-rail" aria-label={`Sharing scope for ${selectedGroup.name}`}>
      <div className="gw-scope-heading"><div><span className="gw-kicker">SHARING SCOPE</span><h2>This group can see</h2></div><span className="gw-draft-pill">Draft</span></div>
      <div className="gw-scope-notice"><span aria-hidden="true">●</span> HomeHub has not issued a permission</div>
      <div className="gw-scope-summary"><strong>{effective.length}</strong><span>items included</span><i>·</i><strong>{draft.added.length}</strong><span>added</span><i>·</i><strong>{draft.excluded.length}</strong><span>hidden</span></div>
      <section className="gw-defaults" aria-labelledby="gw-defaults-title"><div className="gw-section-title"><div><span className="gw-kicker">GROUP OVERRIDES</span><h3 id="gw-defaults-title">Layer access</h3></div><span>{inherited.length} inherited</span></div><p>This group starts with your map defaults. Toggle a layer here to add or hide its items in this group draft.</p><div className="gw-layer-toggles">{privacyLayers.map((layer) => { const layerItems = items.filter((item) => item.layer === layer.id); const included = layerItems.length > 0 && layerItems.every((item) => effective.some((selected) => selected.id === item.id)); return <button type="button" key={layer.id} className={`gw-layer-toggle ${layerClass[layer.id]} ${included ? "is-on" : ""}`} onClick={() => toggleGroupLayer(layer.id)} aria-pressed={included}><span className="gw-layer-swatch" /><span><strong>{layer.label}</strong><small>{layerItems.length} items · {included ? "included" : "hidden"}</small></span><span className="gw-layer-check" aria-hidden="true">{included ? "✓" : "＋"}</span></button>; })}</div></section>
      <section className="gw-scope-items-section" aria-labelledby="gw-visible-title"><div className="gw-section-title"><div><span className="gw-kicker">CURRENT DRAFT</span><h3 id="gw-visible-title">Visible to this group</h3></div>{effective.length > 3 && <span>{effective.length} total</span>}</div><div className="gw-visible-items">{effective.slice(0, 5).map((item) => <ScopeItem key={item.id} item={item} added={draft.added.includes(item.id)} onRemove={() => draft.added.includes(item.id) ? removeAddedItem(conversationId, item.id) : excludeItem(conversationId, item.id)} />)}{!effective.length && <p className="gw-scope-empty">No project data is selected. Add a specific item below.</p>}</div>{effective.length > 5 && <p className="gw-more-scope">＋ {effective.length - 5} more items inherit this draft</p>}</section>
      <section className="gw-add-section"><button type="button" className="gw-add-item" onClick={() => setAddedPickerOpen((open) => !open)} aria-expanded={addedPickerOpen}><span aria-hidden="true">＋</span> Add a specific project item</button>{addedPickerOpen && <div className="gw-add-picker">{candidates.slice(0, 5).map((item) => <button type="button" key={item.id} onClick={() => { addItem(conversationId, item.id); setAddedPickerOpen(false); }}><ItemGlyph item={item} /><span><strong>{item.title}</strong><small>{item.project} · {item.source}</small></span><span aria-hidden="true">＋</span></button>)}{!candidates.length && <p>All inventory items are already in this draft.</p>}</div>}</section>
      <div className="gw-scope-footer"><button type="button" className="gw-reset-scope" onClick={() => resetDraft(conversationId)}>Reset this group</button><button type="button" className="gw-review-button" onClick={onOpenPrivacy}>Review in HomeHub <span aria-hidden="true">→</span></button></div>
    </aside>
  </section>;
}
