import httpx
from adapters.llm import LLMClient


def test_native_tool_history_uses_object_arguments_and_tool_name(monkeypatch):
    captured={}
    def post(url,**kwargs):
        captured.update(kwargs['json'])
        return httpx.Response(200,json={'message':{'content':'done'}},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    client=LLMClient('http://localhost:11434/v1','ami-demo3-qwen')
    client.chat([
        {'role':'assistant','content':'','tool_calls':[{'id':'call0','type':'function','function':{'name':'retrieve','arguments':'{"query":"calls"}'}}]},
        {'role':'tool','tool_call_id':'call0','content':'evidence'},
    ])
    assert captured['messages'][0]['tool_calls'][0]['function']['arguments']=={'query':'calls'}
    assert captured['messages'][1]['tool_name']=='retrieve'
