import sys
from pathlib import Path
import pytest

# Ensure the project root is on sys.path so `ui` package can be imported by pytest
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

# Use the Flask test client to call endpoints in-process (no external server)
from ui import main as ui_main


@pytest.fixture(scope='module')
def client():
    app = ui_main.app
    # Do not call initialize_app() to avoid starting websocket threads
    with app.test_client() as c:
        yield c


def test_search_absorption(client):
    """Search for 'Absorption (4)' and expect at least one matching result."""
    resp = client.get('/api/items/search', query_string={'q': 'Absorption (4)', 'limit': 20})
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code} - {resp.data}"
    data = resp.get_json()
    assert data is not None, "Response did not return JSON"
    assert data.get('success') is True, f"API reported failure: {data}"
    results = data.get('results', [])
    assert isinstance(results, list), "Results should be a list"
    # At least one result should have the exact name
    names = [r.get('name') for r in results]
    assert any(n == 'Absorption (4)' for n in names), f"Absorption (4) not found in results: {names}"


def test_search_empty_query_returns_empty(client):
    resp = client.get('/api/items/search', query_string={'q': '', 'limit': 10})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('success') is True
    assert data.get('results') == []
