#!/usr/bin/env node
/**
 * Build a vendored Understand Anything graph from bridge-owned extraction
 * results. The project root is intentionally not read here: the Python bridge
 * has already staged only Connector-authorized bytes in a temporary directory.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  process.stderr.write("Usage: node ua_graph_builder.mjs <input.json> <output.json>\n");
  process.exit(1);
}

const uaRoot = process.env.UYP_UA_ROOT;
if (!uaRoot) throw new Error("UYP_UA_ROOT is required");
const { GraphBuilder, detectLayers, generateHeuristicTour } = await import(
  pathToFileURL(resolve(uaRoot, "packages/core/dist/index.js")).href,
);

const input = JSON.parse(readFileSync(inputPath, "utf8"));
const results = Array.isArray(input.results) ? input.results : [];
const builder = new GraphBuilder(
  String(input.projectName || "authorized-project"),
  String(input.contentDigest || "unknown"),
);

const knownFiles = new Set(results.map((file) => file.path));
const semanticByPath = input.semanticByPath && typeof input.semanticByPath === "object"
  ? input.semanticByPath
  : {};

for (const file of results) {
  const functions = (file.functions || []).map((fn) => ({
    name: fn.name,
    lineRange: [fn.startLine || 1, fn.endLine || fn.startLine || 1],
    params: fn.params || [],
  }));
  const classes = (file.classes || []).map((cls) => ({
    name: cls.name,
    lineRange: [cls.startLine || 1, cls.endLine || cls.startLine || 1],
    methods: cls.methods || [],
    properties: cls.properties || [],
  }));
  const analysis = { functions, classes, imports: [], exports: [] };
  const semantic = semanticByPath[file.path] || {};
  const summary = semantic.purpose || `Deterministic structure extracted from ${file.path}`;
  const meta = {
    summary,
    tags: [file.language, file.fileCategory, ...(semantic.components || []).slice(0, 3)].filter(Boolean),
    complexity: "simple",
    fileSummary: summary,
    summaries: {},
  };
  for (const item of [...functions, ...classes]) {
    meta.summaries[item.name] = `${item.name} in ${file.path}`;
  }
  if (functions.length || classes.length) builder.addFileWithAnalysis(file.path, analysis, meta);
  else builder.addFile(file.path, { summary, tags: meta.tags, complexity: "simple" });

  // compute-batches may provide resolved import paths. Only create edges to
  // files present in this authorized batch; unresolved imports stay metadata.
  const imports = input.importsByPath?.[file.path] || [];
  for (const target of imports) {
    const targetPath = typeof target === "string" ? target : target?.resolvedPath;
    if (knownFiles.has(targetPath)) builder.addImportEdge(file.path, targetPath);
  }

  for (const call of file.callGraph || []) {
    const caller = String(call.caller || "");
    const callee = String(call.callee || "");
    if (functions.some((fn) => fn.name === caller) && functions.some((fn) => fn.name === callee)) {
      builder.addCallEdge(file.path, caller, file.path, callee);
    }
  }
}
const graph = builder.build();
// Promote bounded Laya/Qwen labels into explicit semantic nodes.  The labels
// are derived metadata only; source bytes remain in the Connector staging
// directory and never enter the graph artifact.
const semanticNodes = new Map();
for (const [filePath, semantic] of Object.entries(semanticByPath)) {
  const fileId = `file:${filePath}`;
  if (!graph.nodes.some((node) => node.id === fileId)) continue;
  const labels = [...(semantic.components || []), ...(semantic.keyPoints || [])]
    .filter((value) => typeof value === "string" && value.trim())
    .map((value) => value.trim().slice(0, 160))
    .slice(0, 6);
  for (const label of labels) {
    const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);
    if (!slug) continue;
    const id = `concept:${slug}`;
    if (!semanticNodes.has(id)) {
      semanticNodes.set(id, {
        id,
        type: "concept",
        name: label,
        summary: `Semantic concept derived from project analysis: ${label}`,
        tags: ["laya-qwen"],
        complexity: "simple",
      });
    }
    const key = `related|${fileId}|${id}`;
    if (!graph.edges.some((edge) => `${edge.type}|${edge.source}|${edge.target}` === key)) {
      graph.edges.push({ source: fileId, target: id, type: "related", direction: "forward", weight: 0.45 });
    }
  }
}
graph.nodes.push(...semanticNodes.values());
graph.layers = detectLayers(graph);
graph.tour = generateHeuristicTour(graph);
writeFileSync(outputPath, JSON.stringify(graph, null, 2));
