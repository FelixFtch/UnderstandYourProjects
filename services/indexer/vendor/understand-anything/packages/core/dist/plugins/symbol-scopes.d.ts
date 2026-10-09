import type { TreeSitterNode as Node } from "./extractors/types.js";
/** Local scope is positive knowledge of separation, never a wildcard. */
export type SymbolScope = {
    kind: "file";
} | {
    kind: "class";
    name: string;
} | {
    kind: "local";
    id: number;
} | {
    kind: "unknown";
};
export declare const FILE_SCOPE: SymbolScope;
export declare const UNKNOWN_SCOPE: SymbolScope;
export declare function namedScope(name: string | null): SymbolScope;
export declare const CLASS_NODES: Set<string>;
export declare const FUNCTION_NODES: Set<string>;
/** A single traversal assigns lexical scopes and value regions. Queries below
 * use those facts; no consumer walks AST ancestors to invent ownership. */
export declare function buildSymbolScopes(root: Node, language: string): {
    declaration: (node: Node) => SymbolScope;
    receiver: (node: Node) => SymbolScope;
    classTarget: (node: Node) => SymbolScope;
    reference(node: Node, name: string): SymbolScope;
    unbound: (node: Node, name: string) => boolean;
};
//# sourceMappingURL=symbol-scopes.d.ts.map