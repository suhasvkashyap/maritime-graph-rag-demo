"""Pattern1 HTTP adapter normalization and failure typing."""

from __future__ import annotations

import json

import httpx
import pytest

from adapters.graph_pattern import GraphPatternClient
from shared.contracts import ToolError


def _transport(handler) -> httpx.HTTPTransport:
    return httpx.HTTPTransport(handler=handler)  # type: ignore[arg-type]


def _drain(request) -> None:
    """Read the request body so closing the socket sends FIN, not RST."""
    length = int(request.headers.get("Content-Length") or 0)
    if length:
        request.rfile.read(length)


def client(handler) -> GraphPatternClient:
    # The client uses module-level httpx functions; patch via respx-style mock
    # by pointing base_url at a local test server built from the handler.
    import httpx
    from httpx import ASGITransport  # noqa: F401
    import threading
    import socket
    from contextlib import closing

    def free_port() -> int:
        with closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    port = free_port()
    server = httpx.HTTPServer if False else None  # placeholder, replaced below

    # Start a tiny WSGI-less server using httpx's ASGITransport is not a server;
    # use Python's http.server for a real socket.
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _respond(self):
            _drain(self)
            status, body = handler(self.path, None, self)
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = _respond

        def log_message(self, *args):  # silence
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return GraphPatternClient(f"http://127.0.0.1:{port}", timeout_seconds=5.0), server


class TestQuery:
    def test_evidence_normalization(self):
        def handler(path, body, request):
            if path == "/v1/retrieve":
                return 200, {
                    "output_text": "Answer text",
                    "evidence": [
                        {
                            "text": "Section D04 (Planned vessel calls): SYN-C101: Atlas Kestrel",
                            "metadata": {
                                "section_id": "D04",
                                "section_title": "Planned vessel calls",
                                "document_id": "ami_maritime_graph_corpus.pdf",
                            },
                        }
                    ],
                }
            return 404, {}

        client_obj, server = client(handler)
        try:
            evidence, answer = client_obj.query("question")
            assert answer == "Answer text"
            assert evidence[0].source_id == "D04"
            assert evidence[0].published_at is not None  # stamped from corpus schedule
            assert evidence[0].origin == "live"
        finally:
            server.shutdown()

    def test_backend_unavailable_is_typed(self):
        client_obj = GraphPatternClient("http://127.0.0.1:9", timeout_seconds=1.0)
        with pytest.raises(ToolError) as excinfo:
            client_obj.query("question")
        assert excinfo.value.error_code.value == "backend_unavailable"

    def test_malformed_json_is_backend_error(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        import socket
        from contextlib import closing

        with closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                _drain(self)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "9")
                self.end_headers()
                self.wfile.write(b"{not json")

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client_obj = GraphPatternClient(f"http://127.0.0.1:{port}", timeout_seconds=5.0)
            with pytest.raises(ToolError) as excinfo:
                client_obj.query("question")
            assert excinfo.value.error_code.value == "backend_error"
        finally:
            server.shutdown()


class TestGraphInspection:
    def test_graph_evidence_shapes(self):
        def handler(path, body, request):
            if path.startswith("/v1/graph/evidence"):
                assert "entities=" in path
                return 200, {
                    "collection": "ai4rag_ami_demo3_local",
                    "nodes": [{"name": "SYN-C101", "type_labels": ["Event"]}],
                    "edges": [
                        {"source": "SYN-C101", "relationship": "LOCATED_IN", "target": "SYN-B04", "chunks": []}
                    ],
                    "matched_seeds": ["syn-c101"],
                    "unmatched": [],
                }
            return 404, {}

        client_obj, server = client(handler)
        try:
            payload = client_obj.graph_evidence(["SYN-C101"])
            assert payload["nodes"][0]["name"] == "SYN-C101"
            assert payload["edges"][0]["relationship"] == "LOCATED_IN"
        finally:
            server.shutdown()

    def test_graph_status(self):
        def handler(path, body, request):
            return 200, {"collection": "c", "available": True, "entities": 42, "relationships": 57}

        client_obj, server = client(handler)
        try:
            assert client_obj.graph_status()["available"] is True
        finally:
            server.shutdown()
