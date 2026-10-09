import type { TreeSitterNode as Node } from "./extractors/types.js";
import type { SymbolEvidenceEntry } from "./symbol-evidence.js";
import { type SymbolScope } from "./symbol-scopes.js";
export declare const COVERAGE_LANGUAGES: Set<string>;
export declare function declarationGap(node: Node, scope: SymbolScope, receiver: SymbolScope): SymbolEvidenceEntry | null;
//# sourceMappingURL=symbol-coverage.d.ts.map