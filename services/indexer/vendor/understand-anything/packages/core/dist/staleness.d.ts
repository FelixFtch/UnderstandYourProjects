import type { KnowledgeGraph, GraphNode, GraphEdge } from "./types.js";
export interface StalenessResult {
    stale: boolean;
    changedFiles: string[];
}
export type GraphFreshnessRelation = "behind" | "ahead" | "diverged";
export type GraphFreshnessUnknownReason = "missing-graph-commit" | "git-head-unavailable" | "graph-commit-unavailable" | "git-command-timeout" | "freshness-request-failed";
export type GraphFreshnessResult = {
    status: "fresh";
    graphCommitHash: string;
    headCommitHash: string;
    changedFileCount: 0;
    changedFiles: [];
    commitsBehind: 0;
    commitsAhead: 0;
    lastAnalyzedAt?: string;
} | {
    status: "dirty";
    graphCommitHash: string;
    headCommitHash: string;
    changedFileCount: number;
    changedFiles: string[];
    commitsBehind: 0;
    commitsAhead: 0;
    lastAnalyzedAt?: string;
} | {
    status: "stale";
    relation: GraphFreshnessRelation;
    graphCommitHash: string;
    headCommitHash: string;
    changedFileCount: number;
    changedFiles: string[];
    commitsBehind: number;
    commitsAhead: number;
    lastAnalyzedAt?: string;
} | {
    status: "unknown";
    reason: GraphFreshnessUnknownReason;
    graphCommitHash?: string;
    headCommitHash?: string;
    lastAnalyzedAt?: string;
};
export interface GraphFreshnessInput {
    graphCommitHash?: string | null;
    lastAnalyzedAt?: string;
}
/**
 * Get the list of files that changed between a given commit and HEAD.
 * Returns an empty array if there are no changes or if git encounters an error.
 */
export declare function getChangedFiles(projectDir: string, lastCommitHash: string): string[];
/**
 * Check whether the knowledge graph is stale relative to the current HEAD.
 */
export declare function isStale(projectDir: string, lastCommitHash: string): StalenessResult;
/**
 * Describe the freshness of multiple persisted graphs against one Git snapshot.
 */
export declare function getGraphFreshnessBatch<T extends string>(projectDir: string, inputs: Record<T, GraphFreshnessInput>): Promise<Record<T, GraphFreshnessResult>>;
/**
 * Describe whether a persisted graph can still be trusted for the project.
 *
 * Unknown is intentionally distinct from fresh: if Git metadata cannot be
 * read, callers should warn softly rather than imply the graph is current.
 */
export declare function getGraphFreshness(projectDir: string, input: GraphFreshnessInput): Promise<GraphFreshnessResult>;
/**
 * Merge new analysis results into an existing knowledge graph.
 *
 * 1. Remove old nodes belonging to changed files (matched by filePath).
 * 2. Remove old edges where the SOURCE or TARGET node belongs to a changed file.
 * 3. Add new nodes and edges.
 * 4. Update project.gitCommitHash and project.analyzedAt.
 * 5. Return the merged graph.
 */
export declare function mergeGraphUpdate(existingGraph: KnowledgeGraph, changedFilePaths: string[], newNodes: GraphNode[], newEdges: GraphEdge[], newCommitHash: string): KnowledgeGraph;
//# sourceMappingURL=staleness.d.ts.map