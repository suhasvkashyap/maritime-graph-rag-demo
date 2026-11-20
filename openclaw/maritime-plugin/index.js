import { spawn } from "node:child_process";
import path from "node:path";

export function runBridge(repoRoot, params, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn(path.join(repoRoot, ".venv/bin/python"),
      ["-m", "adapters.openclaw_bridge"], {
        cwd: repoRoot, shell: false, stdio: ["pipe", "pipe", "pipe"], signal,
        env: { ...process.env, AMI_AGENT_MODE: "live", AMI_DATA_MODE: "live",
               AMI_EXECUTION_MODE: "openshell", AMI_REQUEST_TIMEOUT_SECONDS: "180" },
      });
    let output = "";
    const timeout = setTimeout(() => child.kill("SIGTERM"), 230_000);
    child.stdout.on("data", chunk => {
      output += chunk;
      if (output.length > 2_000_000) child.kill("SIGTERM");
    });
    // Drain diagnostics without leaking them into the model conversation.
    child.stderr.resume();
    child.stdin.on("error", () => {});
    child.on("error", error => { clearTimeout(timeout); reject(error); });
    child.on("close", () => {
      clearTimeout(timeout);
      try { resolve(JSON.parse(output)); }
      catch { reject(new Error("Investigator returned no valid result; check local services.")); }
    });
    child.stdin.end(JSON.stringify(params));
  });
}

export default {
  id: "ami-maritime",
  name: "AMI Maritime Investigator",
  register(api) {
    const repoRoot = api.pluginConfig?.repoRoot;
    if (!repoRoot || !path.isAbsolute(repoRoot)) throw new Error("repoRoot must be an absolute path");
    api.registerTool({
      name: "investigate_port_impact",
      label: "Investigate maritime port impact",
      description: "Delegate a SYN-N017 maritime investigation to the existing specialist inside OpenShell. Returns validated overlaps, shipments, citations and complete/partial/failed status. Call separately for each historical cutoff. Can take up to 3 minutes. Never invent a result when this tool fails.",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          question: { type: "string", minLength: 3, maxLength: 2000 },
          as_of: { type: "string", description: "Explicit ISO-8601 cutoff with timezone. Current exercise: 2026-11-17T12:00:00Z; previous day: 2026-11-16T12:00:00Z." },
        }, required: ["question", "as_of"],
      },
      async execute(_id, params, signal) {
        try {
          const details = await runBridge(repoRoot, params, signal);
          return { content: [{ type: "text", text: JSON.stringify(details) }], details,
                   isError: !details.ok };
        } catch {
          const details = { ok: false, status: "failed", message: "Delegation could not finish. No local or fixture fallback was used." };
          return { content: [{ type: "text", text: JSON.stringify(details) }], details, isError: true };
        }
      },
    });
  },
};
