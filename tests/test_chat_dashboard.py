from fastapi.testclient import TestClient
from contextbridge.dashboard import app


def test_chat_config_endpoint_does_not_expose_credentials() -> None:
    client=TestClient(app)
    data=client.get('/api/chat/config').json()
    assert 'api_key' not in data
    assert 'gemini_api_key' not in data
    assert data['credentials_exposed_to_browser'] is False


def test_chat_session_crud() -> None:
    client=TestClient(app)
    created=client.post('/api/chat/sessions', json={'title':'Test chat'})
    assert created.status_code == 200
    sid=created.json()['session_id']
    detail=client.get(f'/api/chat/sessions/{sid}')
    assert detail.status_code == 200
    assert detail.json()['session']['title'] == 'Test chat'
