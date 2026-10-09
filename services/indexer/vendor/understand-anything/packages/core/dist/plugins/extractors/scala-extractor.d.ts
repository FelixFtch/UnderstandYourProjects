import type { StructuralAnalysis, CallGraphEntry } from "../../types.js";
import type { LanguageExtractor, TreeSitterNode } from "./types.js";
/**
 * Scala extractor for tree-sitter structural analysis and call graph
 * extraction. Covers Scala 2 and Scala 3 syntax: classes, case classes,
 * traits, objects, enums, top-level and member functions, extension
 * methods, and the three import shapes (plain, selector list, wildcard).
 */
export declare class ScalaExtractor implements LanguageExtractor {
    readonly languageIds: string[];
    extractStructure(rootNode: TreeSitterNode): StructuralAnalysis;
    extractCallGraph(rootNode: TreeSitterNode): CallGraphEntry[];
    /**
     * Walk the direct children of the compilation unit (or of a braceless
     * `package foo { ... }` / top-level region) and dispatch declarations.
     */
    private walkTopLevel;
    private extractFunction;
    /**
     * Extract a class / trait / object / enum definition. Nested type
     * definitions inside the body (the companion-object ADT idiom:
     * `object Command { case class Create(...) }`) are recursed into and
     * surfaced as their own class entries.
     */
    private extractTypeDefinition;
    /**
     * Walk a `template_body` / `enum_body` and collect member functions and
     * fields. Function entries are added to both the type's `methods` array
     * and the top-level `functions` array (matching the Go / Swift / Kotlin
     * extractor convention).
     */
    private collectTemplateBody;
    /**
     * Extract a Scala import. The dotted prefix is a run of direct
     * `identifier` children; the trailing element decides the shape:
     *
     * - `import cats.effect.IO`          → source="cats.effect.IO", specifiers=["IO"]
     * - `import cats.effect._` / `.*`    → source="cats.effect",    specifiers=["*"]
     * - `import a.{B, C => D, E as F}`   → source="a",               specifiers=["B", "D", "F"]
     */
    private extractImport;
    private extractImportItem;
    /**
     * Extract the imported names from a `{ ... }` selector list. Renames
     * (`A => B` in Scala 2, `A as B` in Scala 3) surface the source name so
     * file resolution can still probe `A.scala`; excluded `A => _` selectors
     * are skipped. `given` / `*` selectors surface as "*".
     */
    private extractSelectorSpecifiers;
    private extractExtensionDefinition;
    private extractExportDeclaration;
    private extractExportSelectorNames;
    private extractExportedPathName;
    /**
     * Extract the callee name from a Scala `call_expression`. Shapes:
     *
     *   foo(...)                → identifier "foo"
     *   target.method(...)      → field_expression whose last identifier is
     *                             the method name
     *   foo[T](...) / x.f[T](…) → generic_function wrapping either shape
     */
    private extractCallLikeName;
    private extractCalleeName;
    private extractInfixName;
    private extractConstructorName;
}
//# sourceMappingURL=scala-extractor.d.ts.map