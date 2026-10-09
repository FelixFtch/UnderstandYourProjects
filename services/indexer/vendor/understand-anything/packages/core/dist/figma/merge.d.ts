import type { GraphNode, GraphEdge, ProjectMeta } from "../types.js";
import { type ValidationResult } from "../schema.js";
export interface DesignAnalysis {
    nodes?: Array<Pick<GraphNode, "id"> & Partial<Pick<GraphNode, "summary" | "tags">>>;
    edges?: GraphEdge[];
}
export declare function mergeDesignGraph(manifest: {
    nodes: GraphNode[];
    edges: GraphEdge[];
}, analyses: DesignAnalysis[], project: ProjectMeta): ValidationResult;
//# sourceMappingURL=merge.d.ts.map