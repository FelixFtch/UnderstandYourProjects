import type { KnowledgeGraph, AnalysisMeta, ProjectConfig } from "../types.js";
import type { FingerprintStore } from "../fingerprint.js";
/**
 * Resolve the data directory NAME for a project. Projects analyzed before
 * the `.ua` rename keep their existing `.understand-anything/` for both
 * reads and writes (no migration needed); fresh projects get `.ua/`.
 */
export declare function resolveUaDirName(projectRoot: string): string;
/** Absolute path of the project's data directory (see resolveUaDirName). */
export declare function resolveUaDir(projectRoot: string): string;
export declare function saveGraph(projectRoot: string, graph: KnowledgeGraph): void;
export declare function loadGraph(projectRoot: string, options?: {
    validate?: boolean;
}): KnowledgeGraph | null;
export declare function saveMeta(projectRoot: string, meta: AnalysisMeta): void;
export declare function loadMeta(projectRoot: string): AnalysisMeta | null;
export declare function saveFingerprints(projectRoot: string, store: FingerprintStore): void;
export declare function loadFingerprints(projectRoot: string): FingerprintStore | null;
export declare function saveConfig(projectRoot: string, config: ProjectConfig): void;
export declare function loadConfig(projectRoot: string): ProjectConfig;
export declare function saveDomainGraph(projectRoot: string, graph: KnowledgeGraph): void;
export declare function loadDomainGraph(projectRoot: string, options?: {
    validate?: boolean;
}): KnowledgeGraph | null;
//# sourceMappingURL=index.d.ts.map