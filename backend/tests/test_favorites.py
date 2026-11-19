from fastapi.testclient import TestClient
from tradeprism.api import app
from tradeprism.db import session, Favorite

ALICE={'Authorization':'Bearer test-alice-key-at-least-24-chars'}
BOB={'Authorization':'Bearer test-bob-key-at-least-24-chars'}

def test_favorites_persist_are_private_and_idempotent():
    with TestClient(app) as c:
        assert c.get('/favorites').status_code==401
        assert c.put('/favorites/AXISBANK').status_code==401
        assert c.delete('/favorites/AXISBANK').status_code==401
        assert c.get('/favorites',headers=ALICE).json()==[]
        for _ in range(2):
            assert c.put('/favorites/AXISBANK',headers=ALICE).status_code==200
        assert c.get('/favorites',headers=ALICE).json()==['AXISBANK']
        assert c.get('/favorites',headers=BOB).json()==[]
        c.delete('/favorites/AXISBANK',headers=BOB)
        assert c.get('/favorites',headers=ALICE).json()==['AXISBANK']
    # A new application lifespan/client reads the persisted database.
    with TestClient(app) as c:
        assert c.get('/favorites',headers=ALICE).json()==['AXISBANK']
        for _ in range(2):
            assert c.delete('/favorites/AXISBANK',headers=ALICE).status_code==200
        assert c.get('/favorites',headers=ALICE).json()==[]

def test_unknown_stock_rejected_but_delisted_favorite_can_be_removed():
    with TestClient(app) as c:
        assert c.put('/favorites/UNKNOWN_STOCK_TEST',headers=ALICE).status_code==422
        with session() as s:
            s.add(Favorite(owner='alice',symbol='DELISTED_TEST',created=1))
        assert c.get('/favorites',headers=ALICE).json()==['DELISTED_TEST']
        assert c.delete('/favorites/DELISTED_TEST',headers=ALICE).status_code==200
        assert c.get('/favorites',headers=ALICE).json()==[]
