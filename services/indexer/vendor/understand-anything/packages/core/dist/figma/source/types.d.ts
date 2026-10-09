export interface FigmaNode {
    id: string;
    name: string;
    type: string;
    children?: FigmaNode[];
    componentId?: string;
    absoluteBoundingBox?: {
        width: number;
        height: number;
    } | null;
    styles?: Record<string, string>;
    transitionNodeID?: string | null;
}
export interface FigmaDocument {
    name: string;
    document: FigmaNode;
    components?: Record<string, {
        key: string;
        name: string;
        componentSetId?: string;
    }>;
    componentSets?: Record<string, {
        key: string;
        name: string;
    }>;
    styles?: Record<string, {
        key: string;
        name?: string;
        styleType?: string;
    }>;
    version?: string;
    lastModified?: string;
}
export interface FigmaStyles {
    meta?: {
        styles?: Array<{
            key: string;
            name: string;
            style_type: string;
        }>;
    };
}
export interface FigmaSource {
    fetchDocument(): Promise<FigmaDocument>;
    fetchStyles(): Promise<FigmaStyles>;
    renderImages(nodeIds: string[]): Promise<Record<string, string>>;
}
//# sourceMappingURL=types.d.ts.map