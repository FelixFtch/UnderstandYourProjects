import type { StructuralAnalysis } from "../types.js";
import type { TreeSitterNode as Node } from "./extractors/types.js";
import { type SymbolScope } from "./symbol-scopes.js";
/** Runtime possibilities and declaration coverage use explicit scope kinds. */
export interface SymbolEvidenceEntry {
    kind: "callable" | "class" | null;
    scope: SymbolScope;
    name: string | null;
    nameSuffix?: string;
    lineRange: [number, number];
    reason: string;
}
export interface SymbolEvidence {
    version: 2;
    effects: SymbolEvidenceEntry[];
    functions: Array<{
        name: string;
        scope: SymbolScope;
        lineRange: [number, number];
    }>;
    classes: Array<{
        name: string;
        scope: SymbolScope;
        lineRange: [number, number];
    }>;
    coverage: {
        profile: "structural-declarations-v1";
        gaps: SymbolEvidenceEntry[];
    };
}
/** One AST walk emits scoped possibilities, never file-wide text matches. */
export declare function collectSymbolEvidence(root: Node, structure: StructuralAnalysis, language: string): SymbolEvidence;
//# sourceMappingURL=symbol-evidence.d.ts.map