import type { AnalyzerPlugin, StructuralAnalysis, ImportResolution, CallGraphEntry } from "../types.js";
import type { LanguageConfig } from "../languages/types.js";
import type { LanguageExtractor } from "./extractors/types.js";
import { type SymbolEvidence } from "./symbol-evidence.js";
/**
 * Config-driven tree-sitter plugin.
 *
 * Accepts LanguageConfig objects to determine which languages to support
 * and how to load their WASM grammars. Provides deep structural analysis
 * (functions, classes, imports, exports, call graphs) for all languages
 * with registered extractors: TypeScript, JavaScript, Python, Go, Rust,
 * Java, Ruby, PHP, C/C++, C#, Dart, Kotlin, Swift, and Scala.
 *
 * Languages without tree-sitter configs are gracefully skipped (the LLM
 * agent handles analysis for those).
 */
export declare class TreeSitterPlugin implements AnalyzerPlugin {
    readonly name = "tree-sitter";
    readonly languages: string[];
    private configs;
    private _ParserClass;
    private _languages;
    private _extensionToLang;
    private _parsers;
    private _initialized;
    private extractors;
    /**
     * Create a TreeSitterPlugin with the given language configs.
     * Only configs that have a `treeSitter` field will be loaded.
     * If no configs are provided, defaults to TypeScript and JavaScript.
     *
     * @param configs Language configurations to load
     * @param extractors Optional language extractors; if none provided, registers all builtin extractors
     */
    constructor(configs?: LanguageConfig[], extractors?: LanguageExtractor[]);
    registerExtractor(extractor: LanguageExtractor): void;
    private getExtractor;
    private languageKeyFromPath;
    /**
     * Initialize the plugin by loading the WASM module and all language grammars.
     * Must be called (and awaited) before any synchronous methods.
     */
    init(): Promise<void>;
    /**
     * Create a parser set to the appropriate language for the given file.
     * This is synchronous because all languages are pre-loaded during init().
     */
    private getParser;
    private static emptyStructure;
    analyzeFile(filePath: string, content: string): StructuralAnalysis;
    /**
     * Evidence for destructive structural comparisons. Unlike analyzeFile's
     * best-effort contract, an unavailable grammar or a recovered syntax error
     * must never look like a successfully parsed file with no symbols.
     * Supplemental declarations retain their name and owner, so uncertainty
     * cannot leak from an unrelated class or an ordinary source-code token.
     */
    analyzeFileStrict(filePath: string, content: string): {
        status: "succeeded" | "unsupported" | "failed";
        structure: StructuralAnalysis | null;
        symbolEvidence: SymbolEvidence | null;
        language?: string;
    };
    /**
     * Parse the file ONCE and return both structural analysis and the call
     * graph. `extract-structure.mjs` runs `analyzeFile` then `extractCallGraph`
     * on every code file — two full tree-sitter parses of identical content.
     * Both extractors are pure functions of the same rootNode, so a single
     * parse yields byte-identical results (verified) at ~40% less parse work
     * on the indexing hot path. Callers without this method fall back to the
     * two separate calls.
     */
    analyzeFileFull(filePath: string, content: string): {
        structure: StructuralAnalysis;
        callGraph: CallGraphEntry[];
    };
    resolveImports(filePath: string, content: string): ImportResolution[];
    extractCallGraph(filePath: string, content: string): CallGraphEntry[];
}
//# sourceMappingURL=tree-sitter-plugin.d.ts.map