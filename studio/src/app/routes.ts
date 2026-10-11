// Route registry: the ONLY shared edit point between features (one entry per feature).
// Hash routes: #/<section>/<param?>. Each feature page receives `param` (may be undefined).
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

export interface FeaturePageProps {
  param?: string;
  navigate: (hash: string) => void;
}

export interface RouteDef {
  section: string;
  label: string;
  hint: string;
  page: LazyExoticComponent<ComponentType<FeaturePageProps>>;
}

export const ROUTES: RouteDef[] = [
  { section: "jarvis", label: "Jarvis", hint: "Your 1:1 chat with Jarvis", page: lazy(() => import("../features/jarvis/JarvisPage")) },
  { section: "agents", label: "Agents", hint: "Contacts, direct and group chats", page: lazy(() => import("../features/agents/AgentsPage")) },
  { section: "devices", label: "Devices", hint: "Computers, folders and project knowledge", page: lazy(() => import("../features/devices/DevicesPage")) },
  { section: "data", label: "Data", hint: "Privacy rings, Home Assistant, scheduling", page: lazy(() => import("../features/data/DataPage")) },
  { section: "flow", label: "Flow", hint: "How Jarvis thinks: the agent flow", page: lazy(() => import("../features/flow/FlowPage")) },
];
