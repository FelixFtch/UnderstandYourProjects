import type { TreeSitterNode as Node } from "./extractors/types.js";
export declare function unescaped(text: string): boolean;
export declare function literal(node: Node | null | undefined): string | null;
export declare function identifier(node: Node | null | undefined): string | null;
export declare function declarationName(node: Node | null | undefined): string | null;
export declare function declarationKey(node: Node): Node | null;
export declare function unwrap(node: Node | null): Node | null;
export declare function classExpression(node: Node): boolean;
//# sourceMappingURL=symbol-ast.d.ts.map