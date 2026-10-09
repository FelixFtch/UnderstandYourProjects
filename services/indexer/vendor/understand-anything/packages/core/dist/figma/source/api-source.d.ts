import type { FigmaSource, FigmaDocument, FigmaStyles } from "./types.js";
export declare function parseFileKey(urlOrKey: string): string;
export declare class FigmaApiSource implements FigmaSource {
    private readonly fileKey;
    private readonly token;
    constructor(fileKey: string, token?: string | undefined);
    private get;
    fetchDocument(): Promise<FigmaDocument>;
    fetchStyles(): Promise<FigmaStyles>;
    renderImages(nodeIds: string[]): Promise<Record<string, string>>;
}
//# sourceMappingURL=api-source.d.ts.map