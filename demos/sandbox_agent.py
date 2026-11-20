"""JSON entry point packaged in the agent image; never imports Streamlit."""
import json
import sys
from dataclasses import replace
from adapters.llm import LLMClient
from adapters.sandbox import MODEL_ENDPOINT, INFERENCE_PROVIDER
from demos.port_impact import PortImpactAnalyst
from shared.configuration import Settings


def run_request(request):
    settings = replace(Settings.load(), agent_mode="live", data_mode="live",
        model_endpoint=MODEL_ENDPOINT, model_api_key="unused",
        model_id=request["model_id"], analysis_cutoff=request["analysis_cutoff"],
        max_tool_calls=max(1, min(int(request["max_tool_calls"]), 12)),
        request_timeout_seconds=max(1, min(float(request["request_timeout_seconds"]), 600)))
    llm = LLMClient(settings.model_endpoint, settings.model_id, "unused", timeout_seconds=60)
    analyst = PortImpactAnalyst(settings, llm=llm, policy_challenge=request.get("challenge", False))
    result = analyst.run(request["question"], request["analysis_cutoff"], scripted=False)
    result.demo_specific_result["document_requests"] = analyst.document_requests
    result.demo_specific_result["execution"] = {"runtime": "openshell", "model_endpoint": settings.model_endpoint,
                                                  "inference_provider": INFERENCE_PROVIDER}
    return {"runtime": "openshell", "model_endpoint": settings.model_endpoint,
            "result": result.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in analyst.last_evidence()],
            "requests": analyst.document_requests, "model_calls": llm.model_calls}


if __name__ == "__main__":
    print(json.dumps(run_request(json.loads(sys.argv[1]))))
