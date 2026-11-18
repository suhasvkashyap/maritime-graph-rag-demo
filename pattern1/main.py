"""AMI Demo 3 local Graph AutoRAG service (Pattern1, laptop-local variant).

Generated starter-kit service, extended locally for the Port Impact
Investigator demo:

* ``POST /v1/responses`` additionally returns the evidence documents that the
  Graph AutoRAG run actually retrieved (``evidence``), so the demo application
  can cite real retrieved passages instead of a bare answer string.
* ``GET /v1/graph/status`` and ``GET /v1/graph/evidence`` expose a strictly
  allowlisted, parameterized, read-only inspection of the extracted knowledge
  graph for the configured demo collection. Clients cannot issue arbitrary
  Cypher; every query template is fixed below and sessions are opened
  read-only.

Run locally against Ollama + a local Neo4j (see ../README.md).
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path
from typing import Any, Literal

import neo4j
import openai
from dotenv import load_dotenv

# The service reads MAAS_BASE_URL / Neo4j / collection settings from the
# process environment; load the kit's .env so a bare `uvicorn main:app`
# works the same way the indexing script does.
load_dotenv(Path(__file__).resolve().parent / ".env")
from agentic_rag.agent import create_rag  # noqa: E402  (needs env loaded)
from agentic_rag.config import AgentConfig  # noqa: E402
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

logger = logging.getLogger(__name__)
RAG = None
DEFAULT_APP_PORT = 8000

_MAX_INVOKE_ATTEMPTS = 3
_GRACEFUL_ERROR_MESSAGE = "I was unable to process this request due to repeated internal errors."
_RETRYABLE_EXCEPTIONS = (
    openai.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
)

# Allowlisted relationship types for graph inspection. The KG pipeline used
# constrained extraction, so these are the only entity-to-entity relationship
# types that can exist.
_ALLOWED_REL_TYPES = {"RELATED_TO", "PART_OF", "LOCATED_IN", "BELONGS_TO", "CREATED_BY", "MENTIONS"}
_MAX_SEED_ENTITIES = 8
_MAX_NAME_LENGTH = 96
_SCHEMA_ENTITY_LABEL = "__Entity__"
_SCHEMA_CHUNK_LABEL = "Chunk"


class ResponseInputMessage(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(..., examples=["user", "assistant", "system"])
    content: str


class ResponsesRequest(BaseModel):
    input: str | list[ResponseInputMessage]
    model: str | None = None
    instructions: str | None = None
    stream: bool = False


class ResponseOutputText(BaseModel):
    type: str = "output_text"
    text: str


class ResponseMessage(BaseModel):
    id: str
    type: str = "message"
    status: str = "completed"
    role: str = "assistant"
    content: list[ResponseOutputText]


class ResponsesResponse(BaseModel):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    model: str
    status: str = "completed"
    output: list[ResponseMessage]
    output_text: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict | None = None


class HealthResponse(BaseModel):
    status: str
    agent_initialized: bool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global RAG
    RAG = create_rag()
    app.state.rag = RAG
    app.state.config = RAG.retriever._vector_store._config  # noqa: SLF001 - same-process configuration reuse
    app.state.collection = RAG.retriever._vector_store._collection_name  # noqa: SLF001
    app.state.driver = RAG.retriever._vector_store._driver  # noqa: SLF001
    yield
    RAG = None
    app.state.rag = None


app = FastAPI(
    title="Agentic RAG API (AMI Demo 3 local)",
    description=("Graph AutoRAG service with evidence return and allowlisted read-only graph inspection."),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Health", "description": "Service health monitoring"},
        {"name": "Responses", "description": "Responses API operations"},
        {"name": "Graph", "description": "Allowlisted read-only extracted-graph inspection"},
    ],
)


def _make_response_id() -> str:
    return f"resp-{uuid.uuid4().hex[:12]}"


def _evidence_payload(chunks: list[Any]) -> list[dict[str, Any]]:
    """Return the JSON-safe form of chunks the pattern actually retrieved."""
    evidence = []
    for chunk in chunks:
        evidence.append(
            {
                "text": chunk.text,
                "metadata": json.loads(json.dumps(dict(chunk.metadata), default=str)),
            }
        )
    return evidence


async def _invoke_with_retry(question: str) -> dict[str, Any]:
    if RAG is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    last_exception: Exception = RuntimeError("no invocation attempts were made")
    for attempt in range(1, _MAX_INVOKE_ATTEMPTS + 1):
        try:
            result = await asyncio.to_thread(RAG.generate, question)
            return {
                "content": str(result.get("answer") or ""),
                "evidence": _evidence_payload(list(result.get("reference_documents") or [])),
            }
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exception = exc
            if attempt < _MAX_INVOKE_ATTEMPTS:
                logger.warning(
                    "RAG invocation failed (attempt %d/%d): %s",
                    attempt,
                    _MAX_INVOKE_ATTEMPTS,
                    type(exc).__name__,
                )
                await asyncio.sleep(0.5 * attempt)

    raise last_exception


@app.post(
    "/v1/responses",
    response_model=ResponsesResponse,
    summary="Create a model response with retrieved evidence",
    tags=["Responses"],
)
async def responses(request: ResponsesRequest):
    if isinstance(request.input, str):
        question = request.input
    else:
        user_messages = [message.content for message in request.input if message.role == "user"]
        question = user_messages[-1] if user_messages else ""
    if not question.strip():
        raise HTTPException(status_code=400, detail="A non-empty user message is required.")
    model_id = request.model or (RAG.foundation_model.model_id if RAG else None)

    try:
        result = await _invoke_with_retry(question)
    except _RETRYABLE_EXCEPTIONS as exc:
        logger.exception("RAG invocation failed", exc_info=exc)
        raise HTTPException(status_code=503, detail=_GRACEFUL_ERROR_MESSAGE) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error processing request: {exc}") from exc

    response_id = _make_response_id()
    if request.stream:
        return _stream_response(response_id, model_id, result["content"])

    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "model": model_id,
        "status": "completed",
        "output": [
            {
                "id": f"msg-{uuid.uuid4().hex[:12]}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": result["content"]}],
            }
        ],
        "output_text": result["content"],
        "evidence": result["evidence"],
        "usage": None,
    }


def _stream_response(response_id: str, model_id: str, content: str) -> StreamingResponse:

    async def event_generator() -> AsyncIterator[str]:
        data = {
            "type": "response.output_text.delta",
            "response_id": response_id,
            "delta": content,
        }
        yield f"data: {json.dumps(data)}\n\n"
        yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': response_id, 'object': 'response', 'model': model_id, 'status': 'completed'}})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class RetrievalRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)


@app.post("/v1/retrieve", tags=["Graph"])
async def retrieve(request: RetrievalRequest):
    """Graph retrieval only; the caller's agent performs reasoning, once.

    For this bounded 12-section exercise packet, retrieve all sections so
    a low semantic rank cannot silently hide a schedule correction.
    """
    if RAG is None:
        raise HTTPException(status_code=503, detail="Retriever not initialized")
    chunks = await asyncio.to_thread(RAG.retriever.retrieve, request.input)
    return {"evidence": _evidence_payload(chunks), "output_text": "",
            "retrieval_mode": "graph", "scope": "12-section exercise packet"}


# ---------------------------------------------------------------------------
# Allowlisted read-only graph inspection
# ---------------------------------------------------------------------------

_SEED_QUERY = (
    f"MATCH (e:{_SCHEMA_ENTITY_LABEL}) "
    "WHERE toLower(e.name) IN $names AND $col IN COALESCE(e.ai4rag_kg_collections, []) "
    "RETURN DISTINCT elementId(e) AS eid, e.name AS name, "
    "[l IN labels(e) WHERE NOT l IN ['__Entity__', '__KGBuilder__']] AS type_labels "
    "LIMIT $max_nodes"
)

_NEIGHBOR_QUERY = (
    f"MATCH (a:{_SCHEMA_ENTITY_LABEL})-[r]-(b:{_SCHEMA_ENTITY_LABEL}) "
    "WHERE elementId(a) IN $seed_ids AND $col IN COALESCE(r.ai4rag_kg_collections, []) "
    "AND ($col IN COALESCE(b.ai4rag_kg_collections, [])) AND type(r) IN $allowed_types "
    "RETURN DISTINCT elementId(b) AS eid, b.name AS name, "
    "[l IN labels(b) WHERE NOT l IN ['__Entity__', '__KGBuilder__']] AS type_labels "
    "LIMIT $max_nodes"
)

_EDGE_QUERY = (
    f"MATCH (a:{_SCHEMA_ENTITY_LABEL})-[r]->(b:{_SCHEMA_ENTITY_LABEL}) "
    "WHERE elementId(a) IN $node_ids AND elementId(b) IN $node_ids "
    "AND type(r) IN $allowed_types AND $col IN COALESCE(r.ai4rag_kg_collections, []) "
    "RETURN elementId(a) AS source_id, a.name AS source_name, type(r) AS rel_type, r.predicate AS predicate, r.source_chunk_id AS source_chunk_id, "
    "elementId(b) AS target_id, b.name AS target_name, elementId(r) AS eid "
    "LIMIT $max_edges"
)

_EDGE_PROVENANCE_QUERY = (
    "MATCH (e:{entity_label})-[:FROM_CHUNK]->(c:`{collection}`:`{chunk_label}`) "
    "MATCH (other:{entity_label})-[:FROM_CHUNK]->(c) "
    "WHERE elementId(e) = $source_id AND elementId(other) = $target_id AND c.collection = $col "
    "RETURN c.id AS chunk_id, c.text AS text, c.metadata AS metadata "
    "LIMIT 2"
)

_SUMMARY_QUERY = (
    f"MATCH (e:{_SCHEMA_ENTITY_LABEL}) WHERE $col IN COALESCE(e.ai4rag_kg_collections, []) "
    "WITH count(e) AS entities "
    f"MATCH ()-[r]->() WHERE $col IN COALESCE(r.ai4rag_kg_collections, []) AND type(r) IN $allowed_types "
    "RETURN entities, count(r) AS relationships"
)


def _read_session() -> neo4j.Session:
    driver: neo4j.Driver = app.state.driver
    return driver.session(default_access_mode=neo4j.READ_ACCESS, database=app.state.config.database)


def _normalize_names(raw: str) -> list[str]:
    names = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if len(token) > _MAX_NAME_LENGTH:
            raise HTTPException(status_code=400, detail="Entity name too long.")
        names.append(token)
    if not names:
        raise HTTPException(status_code=400, detail="Provide at least one entity name.")
    if len(names) > _MAX_SEED_ENTITIES:
        raise HTTPException(status_code=400, detail=f"At most {_MAX_SEED_ENTITIES} entity names are allowed.")
    return names


@app.get("/v1/graph/status", summary="Extracted-graph availability for the demo collection", tags=["Graph"])
async def graph_status():
    with _read_session() as session:
        row = session.run(
            _SUMMARY_QUERY,
            col=app.state.collection,
            allowed_types=sorted(_ALLOWED_REL_TYPES),
        ).single()
    if row is None:
        return {"collection": app.state.collection, "available": False, "entities": 0, "relationships": 0}
    return {
        "collection": app.state.collection,
        "construction": "source_parsed",
        "available": bool(row["entities"] and row["relationships"]),
        "entities": row["entities"],
        "relationships": row["relationships"],
    }


@app.get("/v1/graph/evidence", summary="Extracted entity neighborhood with chunk provenance", tags=["Graph"])
async def graph_evidence(
    entities: str = Query(..., description="Comma-separated entity names (case-insensitive)."),
    max_nodes: int = Query(15, ge=1, le=25),
    max_edges: int = Query(20, ge=1, le=35),
):
    names = _normalize_names(entities)
    with _read_session() as session:
        seed_rows = session.run(
            _SEED_QUERY,
            names=names,
            col=app.state.collection,
            max_nodes=max_nodes,
        ).data()
        if not seed_rows:
            return {
                "collection": app.state.collection,
                "nodes": [],
                "edges": [],
                "matched_seeds": [],
                "unmatched": [n for n in names],
            }
        seed_ids = [row["eid"] for row in seed_rows]
        neighbor_rows = session.run(
            _NEIGHBOR_QUERY,
            seed_ids=seed_ids,
            allowed_types=sorted(_ALLOWED_REL_TYPES),
            col=app.state.collection,
            max_nodes=max_nodes,
        ).data()
        node_rows: dict[str, dict[str, Any]] = {}
        for row in [*seed_rows, *neighbor_rows]:
            node_rows[row["eid"]] = {"id": row["eid"], "name": row["name"], "type_labels": row["type_labels"]}
        edge_rows = session.run(
            _EDGE_QUERY,
            node_ids=list(node_rows)[:max_nodes],
            col=app.state.collection,
            allowed_types=sorted(_ALLOWED_REL_TYPES),
            max_edges=max_edges,
        ).data()
        edges = []
        for row in edge_rows:
            provenance_query = ("MATCH (c:Chunk {id:$chunk_id,collection:$col}) RETURN c.id AS chunk_id,c.text AS text,c.metadata AS metadata" if row.get("source_chunk_id") else _EDGE_PROVENANCE_QUERY.format(entity_label=_SCHEMA_ENTITY_LABEL,collection=app.state.collection,chunk_label=_SCHEMA_CHUNK_LABEL))
            provenance = session.run(
                provenance_query,
                chunk_id=row.get("source_chunk_id"),
                source_id=row["source_id"],
                target_id=row["target_id"],
                col=app.state.collection,
            ).data()
            chunks = []
            for prov in provenance:
                metadata = {}
                try:
                    metadata = json.loads(prov.get("metadata") or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                chunks.append(
                    {
                        "chunk_id": prov.get("chunk_id"),
                        "section_id": metadata.get("section_id"),
                        "excerpt": (prov.get("text") or "")[:220],
                    }
                )
            edges.append(
                {
                    "source": row["source_name"],
                    "relationship": row.get("predicate") or row["rel_type"],
                    "storage_relationship_type": row["rel_type"],
                    "target": row["target_name"],
                    "chunks": chunks,
                    "provenance_kind": "edge_source_chunk" if row.get("source_chunk_id") else "shared_endpoint_chunks",
                }
            )
    matched = {row["name"].lower() for row in seed_rows}
    return {
        "collection": app.state.collection,
        "nodes": list(node_rows.values())[:max_nodes],
        "edges": edges,
        "matched_seeds": sorted(matched),
        "unmatched": [n for n in names if n not in matched],
    }


@app.get("/health", response_model=HealthResponse, summary="Health check", tags=["Health"])
async def health():
    initialized = RAG is not None
    body = {
        "status": "healthy" if initialized else "not_ready",
        "agent_initialized": initialized,
    }
    if not initialized:
        return JSONResponse(status_code=503, content=body)
    return body


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(getenv("PORT", str(DEFAULT_APP_PORT))))
