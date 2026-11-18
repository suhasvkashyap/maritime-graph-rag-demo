"""Regression tests without Neo4j/Ollama or a listening network socket."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from fastapi.testclient import TestClient
from agentic_rag.bounded_model import BoundedFoundationModel


class ServiceContract(unittest.TestCase):
    def test_http_response_preserves_citation_evidence(self):
        evidence = [{"text": "Section D04: SYN-C101", "metadata": {"section_id": "D04"}}]
        with patch.object(main, '_invoke_with_retry', AsyncMock(return_value={'content': 'answer', 'evidence': evidence})):
            response = TestClient(main.app).post('/v1/responses', json={'input': 'question', 'model': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['evidence'], evidence)

    def test_read_session_uses_supported_neo4j_constant(self):
        main.app.state.driver = MagicMock()
        main.app.state.config = SimpleNamespace(database='neo4j')
        main._read_session()
        main.app.state.driver.session.assert_called_once_with(default_access_mode='READ', database='neo4j')

    def test_graph_queries_bind_collection_and_endpoint_ids(self):
        session = MagicMock()
        session.run.return_value.data.side_effect = [
            [{'eid':'n1','name':'SYN-C101','type_labels':[]}],
            [{'eid':'n2','name':'SYN-N017','type_labels':[]}],
            [{'source_id':'n1','target_id':'n2','source_name':'SYN-C101','target_name':'SYN-N017','rel_type':'RELATED_TO','eid':'r1'}],
            [{'chunk_id':'c1','text':'Evidence','metadata':'{"section_id":"D04"}'}],
        ]
        main.app.state.collection='ai4rag_test'
        with patch.object(main,'_read_session') as mock:
            mock.return_value.__enter__.return_value=session
            result=asyncio.run(main.graph_evidence('SYN-C101',15,20))
        calls=session.run.call_args_list
        self.assertEqual(calls[2].kwargs['col'],'ai4rag_test')
        self.assertEqual(calls[3].kwargs['source_id'],'n1')
        self.assertEqual(calls[3].kwargs['target_id'],'n2')
        self.assertEqual(result['edges'][0]['chunks'][0]['section_id'],'D04')

    def test_local_model_does_not_escalate_timeout_or_retry(self):
        client=MagicMock()
        client.chat.completions.create.side_effect=TimeoutError('bounded')
        model=BoundedFoundationModel(client=client,model_id='test')
        with self.assertRaises(TimeoutError):model.chat([{'role':'user','content':'hi'}])
        self.assertEqual(client.chat.completions.create.call_count,1)
        client.with_options.assert_not_called()


if __name__ == '__main__':unittest.main()
