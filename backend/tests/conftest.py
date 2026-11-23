import os
import tempfile
import pytest

# Isolated fixtures never enter the application database or shipped artifacts.
ROOT=tempfile.TemporaryDirectory(prefix='tradeprism-tests-')
os.environ['DATA_DIR']=ROOT.name
os.environ['DATABASE_URL']='sqlite:///'+ROOT.name+'/test.db'
os.environ['TRADEPRISM_USERS']='{"alice":"test-alice-key-at-least-24-chars","bob":"test-bob-key-at-least-24-chars"}'
from tradeprism.db import Base, engine, init

@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    init()
    yield

@pytest.fixture(scope='session', autouse=True)
def close_database_before_temp_cleanup():
    yield
    engine.dispose()
    ROOT.cleanup()
