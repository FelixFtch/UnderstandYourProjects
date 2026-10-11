// Privacy rings editor: one ring + "share with agents" per category, own vs inherited.
import { useState } from "react";
import type { PolicyDoc, PrivacyCategory, PrivacyPolicy, Ring } from "../../api/contracts";
import {
  CATEGORY_INFO, RING_INFO, explainPrivacy, privacyRows, setPrivacy, unsetPath, type PrivacyRow,
} from "./inherit";
import { FieldShell, Icon, RingControl, RingLegend, Toggle } from "./ui";

type Obj = Record<string, unknown>;

export function PrivacyTab({ doc, draft, setDraft, readOnly, parentLabel, isRoot, dirty }: {
  doc: PolicyDoc<PrivacyPolicy>;
  draft: Obj;
  setDraft: (v: Obj) => void;
  readOnly: boolean;
  parentLabel: string | null;
  isRoot: boolean;
  dirty: boolean;
}) {
  const [focus, setFocus] = useState<Ring | undefined>(undefined);
  const rows = privacyRows(draft, doc.inherited, doc.effective);
  const sharedNow = rows.filter((r) => (dirty ? r.local : r.effective)?.share_with_agents && (dirty ? r.local : r.effective)?.ring === "R4");

  function change(cat: PrivacyCategory, patch: { ring?: Ring; share_with_agents?: boolean }) {
    setDraft(setPrivacy(draft, doc.inherited, cat, patch));
  }

  return (
    <div className="dm-privacy">
      <section className="dm-intro">
        <RingLegend highlight={focus} />
        <div className="dm-intro-text">
          <h3>Who may Jarvis tell?</h3>
          <p>Each kind of data sits in a ring. Jarvis answers someone only if they are inside that ring: <b>R1</b> is just you, <b>R4</b> reaches other Jarvis agents outside the house.</p>
          <p><b>Share with agents</b> pre-enables a category on every new agent chat's <a className="dm-link" href="#/agents">share card</a>. It is only possible at R4.</p>
          <p className="dm-muted">
            {sharedNow.length
              ? <>On share cards by default{dirty ? " (after save)" : ""}: {sharedNow.map((r) => CATEGORY_INFO[r.category].label).join(", ")}.</>
              : <>Nothing is shared with agents by default{dirty ? " (after save)" : ""}.</>}
          </p>
        </div>
      </section>

      <div className="dm-fields">
        {rows.map((row) => (
          <PrivacyField key={row.category} row={row} readOnly={readOnly} parentLabel={parentLabel} isRoot={isRoot} dirty={dirty}
            onFocus={() => setFocus(row.local.ring)}
            onChange={(patch) => change(row.category, patch)}
            onReset={() => setDraft(unsetPath(draft, ["categories", row.category]))} />
        ))}
      </div>
    </div>
  );
}

function PrivacyField({ row, readOnly, parentLabel, isRoot, dirty, onChange, onReset, onFocus }: {
  row: PrivacyRow; readOnly: boolean; parentLabel: string | null; isRoot: boolean; dirty: boolean;
  onChange: (patch: { ring?: Ring; share_with_agents?: boolean }) => void; onReset: () => void; onFocus: () => void;
}) {
  const info = CATEGORY_INFO[row.category];
  const shown = dirty ? row.local : (row.effective ?? row.local);
  const explain = explainPrivacy(dirty ? row.local : row.effective);
  const canShare = row.local.ring === "R4";
  const inh = row.inherited;
  const clamped = !dirty && row.effective && (row.effective.ring !== row.local.ring || Boolean(row.effective.share_with_agents) !== row.local.share_with_agents);

  return (
    <div onFocusCapture={onFocus} onMouseEnter={onFocus}>
      <FieldShell
        title={info.label}
        hint={info.hint}
        view={row}
        parentLabel={parentLabel}
        readOnly={readOnly}
        canInherit={!isRoot}
        onReset={onReset}
        footer={
          <div className={`dm-effective dm-ring-${shown.ring ?? "R1"}`}>
            <span className="dm-effective-k">{dirty ? "After save" : "Effective"}</span>
            <span className="dm-effective-v">{explain.headline}</span>
            <span className="dm-effective-d">{explain.detail}</span>
            {row.source === "own" && inh?.ring ? (
              <span className="dm-effective-d">
                {row.overrides ? "Overrides" : "Same as"} inherited {inh.ring} {RING_INFO[inh.ring].label.toLowerCase()}
                {inh.ring === "R4" ? (inh.share_with_agents ? ", shared" : ", not shared") : ""}.
                {row.partial ? " Only part of this setting is set here; the rest is inherited." : ""}
              </span>
            ) : null}
            {clamped ? <span className="dm-effective-d dm-warn"><Icon name="alert" size={12} /> The hub limits this level (for example guests never exceed the household), so the effective value differs from what is set.</span> : null}
          </div>
        }
      >
        <div className="dm-privacy-controls">
          <RingControl value={row.local.ring} disabled={readOnly} label={`${info.label} ring`} onChange={(ring) => onChange({ ring })} />
          <label className={`dm-share${canShare ? "" : " is-off"}`} title={canShare ? "" : "Only R4 (external) data can be shared with other agents"}>
            <Toggle checked={row.local.share_with_agents && canShare} disabled={readOnly || !canShare}
              label={`Share ${info.label} with agents`} onChange={(v) => onChange({ share_with_agents: v })} />
            <span>
              Share with agents
              {!canShare ? <small>needs R4</small> : null}
            </span>
          </label>
        </div>
      </FieldShell>
    </div>
  );
}
