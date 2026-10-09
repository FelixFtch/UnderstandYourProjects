import type { StructuralAnalysis, CallGraphEntry } from "../../types.js";
import type { LanguageExtractor, TreeSitterNode } from "./types.js";
/**
 * Dart extractor for tree-sitter structural analysis + call graph.
 *
 * Approach (matching `KotlinExtractor` convention): mixin / extension / enum
 * declarations are folded into `StructuralAnalysis.classes[]` because the
 * shared schema does not have a first-class slot for them. Extension
 * declarations without a name surface as `"on <TargetType>"` so they aren't
 * silently dropped.
 */
export declare class DartExtractor implements LanguageExtractor {
    readonly languageIds: string[];
    extractStructure(rootNode: TreeSitterNode): StructuralAnalysis;
    private extractTopLevelFunction;
    /**
     * Extract a class-like declaration that uses a `class_body`-shaped member
     * container. Used by `class_definition`, `mixin_declaration`, and (Task 8)
     * `extension_declaration`. The only difference between these shapes is the
     * body's node type name, which is passed in via `bodyNodeType`.
     *
     * When `nameOverride` is provided, it is used as the entry's name instead of
     * looking up a leading `identifier` child — used by anonymous extensions,
     * which have no name in the source.
     */
    private extractClassLikeDeclaration;
    private extractExtensionDeclaration;
    private extractEnumDeclaration;
    private extractImportOrExport;
    private extractLibraryImport;
    /**
     * Extract an `export` directive's URI into `exports[]`.
     *
     * Takes both `libExport` (the `library_export` node containing the URI)
     * and `outerNode` (the wrapping `import_or_export` node). The line number
     * uses `outerNode.startPosition` because `library_export` may start one
     * child deeper than the `export` keyword, while `import_or_export` is
     * guaranteed to start at the keyword.
     */
    private extractLibraryExport;
    extractCallGraph(rootNode: TreeSitterNode): CallGraphEntry[];
    /**
     * Find the callee name for a `selector` node that contains an
     * `argument_part`. Look at the parent's children:
     *   - Bare call `foo(...)`: the previous sibling is an `identifier`.
     *   - Method call `target.foo(...)`: the previous sibling is itself a
     *     `selector` wrapping `unconditional_assignable_selector` with the
     *     method-name `identifier`.
     *
     * Probe finding (2026-06-13): the plan's claimed AST shapes match exactly.
     *   - Bare call:   return_statement > identifier[helper] + selector(argument_part)
     *   - Method call: expression_statement > string_literal + selector(unconditional_assignable_selector > identifier[toUpperCase]) + selector(argument_part)
     * The plan claimed `expression_statement` as parent for bare calls but the
     * actual parent for `return helper()` is `return_statement`. This does not
     * affect the strategy since we only look at the preceding sibling, not the
     * parent type.
     *
     * IMPORTANT: web-tree-sitter returns a NEW wrapper object each time `.child(i)`
     * is called — node identity (`===`) does NOT work for sibling lookup. We
     * compare by `startIndex` (byte offset) which is stable and unique per node.
     */
    private extractCalleeName;
}
//# sourceMappingURL=dart-extractor.d.ts.map