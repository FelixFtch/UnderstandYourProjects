/**
 * Hardcoded default ignore patterns matching the project-scanner agent's
 * exclusion rules, plus bin/obj for .NET projects.
 */
export declare const DEFAULT_IGNORE_PATTERNS: string[];
export interface IgnoreFilter {
    /** Returns true if the given relative path should be excluded from analysis. */
    isIgnored(relativePath: string): boolean;
}
/**
 * Creates an IgnoreFilter that merges hardcoded defaults with user-defined
 * patterns from .understandignore files and CLI-provided exclude patterns.
 *
 * Pattern load order (later entries can override earlier ones via ! negation):
 * 1. Hardcoded defaults
 * 2. <ua-dir>/.understandignore (if exists — `.ua/`, or the legacy
 *    `.understand-anything/` when that directory already exists)
 * 3. .understandignore at project root (if exists)
 * 4. CLI --exclude patterns (highest priority)
 */
export declare function createIgnoreFilter(projectRoot: string, extraPatterns?: string[]): IgnoreFilter;
//# sourceMappingURL=ignore-filter.d.ts.map