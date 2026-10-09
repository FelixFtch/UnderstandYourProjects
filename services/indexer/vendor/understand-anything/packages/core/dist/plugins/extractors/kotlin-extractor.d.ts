import type { StructuralAnalysis, CallGraphEntry } from "../../types.js";
import type { LanguageExtractor, TreeSitterNode } from "./types.js";
/**
 * Kotlin extractor for tree-sitter structural analysis and call graph
 * extraction. Maps Kotlin's class / interface / object / data-class
 * declarations to the project's shared `StructuralAnalysis.classes` array.
 */
export declare class KotlinExtractor implements LanguageExtractor {
    readonly languageIds: string[];
    extractStructure(rootNode: TreeSitterNode): StructuralAnalysis;
    extractCallGraph(rootNode: TreeSitterNode): CallGraphEntry[];
    private extractTopLevelFunction;
    private extractClassDeclaration;
    private extractObjectDeclaration;
    /**
     * Extract a Kotlin import.
     *
     * The grammar gives us a single `qualified_identifier` child holding the
     * dotted module path. Three trailing variants must be distinguished:
     *
     * - `import foo.bar.Baz`            → source="foo.bar.Baz", specifier="Baz"
     * - `import foo.bar.*`              → source="foo.bar",     specifier="*"
     * - `import foo.bar.Baz as Quux`    → source="foo.bar.Baz", specifier="Quux"
     *
     * The grammar represents the wildcard as a trailing `*` token AFTER the
     * qualified_identifier (which holds the dotted prefix). The alias
     * appears as `as` + a top-level `identifier` sibling.
     */
    private extractImport;
    /**
     * Extract the callee name from a Kotlin `call_expression`. Two shapes:
     *
     *   foo(...)              → first child is `identifier "foo"`
     *   target.method(...)    → first child is `navigation_expression` whose
     *                           last `navigation_suffix > identifier` is the
     *                           method name
     */
    private extractCalleeName;
}
//# sourceMappingURL=kotlin-extractor.d.ts.map