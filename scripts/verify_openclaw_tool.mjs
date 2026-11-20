// Live tool-boundary check. This does not claim an OpenClaw conversation passed.
import plugin from "../openclaw/maritime-plugin/index.js";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";
const repoRoot = fileURLToPath(new URL("../", import.meta.url));
let tool;
plugin.register({ pluginConfig: { repoRoot }, registerTool(value) { tool = value; } });
const cutoff = process.argv[2] || "2026-11-17T12:00:00Z";
const response = await tool.execute("live-verification", {
  question: "Which Halcyon subsidiary-operated calls overlap notice SYN-N017, and which shipments are connected?",
  as_of: cutoff,
});
const result = response.details;
writeFileSync(new URL("../.run/openclaw-tool-validation.json", import.meta.url), JSON.stringify(result, null, 2));
console.log(JSON.stringify({ tool: tool.name, status: result.status, runtime: result.runtime,
  overlaps: result.overlaps?.map(o => [o.call_id, o.overlap_hours]), sources: result.sources?.length,
  artifact: result.artifact }));
const expected = cutoff === "2026-11-16T12:00:00Z"
  ? [["SYN-C101", 8], ["SYN-C103", 5]] : [["SYN-C101", 8]];
const actual = result.overlaps?.map(o => [o.call_id, o.overlap_hours]).sort();
if (result.status !== "complete" || result.runtime !== "openshell" || !result.sources?.length ||
    JSON.stringify(actual) !== JSON.stringify(expected)) process.exitCode = 1;
