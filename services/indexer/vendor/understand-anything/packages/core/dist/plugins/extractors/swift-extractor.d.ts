import type { StructuralAnalysis, CallGraphEntry } from "../../types.js";
import type { LanguageExtractor, TreeSitterNode } from "./types.js";
/**
 * Swift extractor for tree-sitter structural analysis and call graph extraction.
 *
 * Swift has more type-like containers than the shared StructuralAnalysis schema
 * can represent directly. Following the existing Dart/Kotlin/Rust conventions,
 * class, struct, enum, actor, protocol, and extension containers are folded into
 * `classes[]`, while callable members are also surfaced in `functions[]`.
 */
export declare class SwiftExtractor implements LanguageExtractor {
    readonly languageIds: string[];
    extractStructure(rootNode: TreeSitterNode): StructuralAnalysis;
    extractCallGraph(rootNode: TreeSitterNode): CallGraphEntry[];
    private extractTopLevelFunction;
    private extractClassLike;
    private extractProtocol;
    private collectBodyMembers;
    private collectFunctionMember;
    private collectInitMember;
    private collectDeinitMember;
    private collectSubscriptMember;
    private collectPropertyMember;
    private collectAssociatedType;
    private extractImport;
    private classLikeName;
    private extractCalleeName;
    private extractNavigationName;
    private extractConstructedType;
}
//# sourceMappingURL=swift-extractor.d.ts.map