import os
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

DATA = Path(os.getenv('DATA_DIR', 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
url = os.getenv('DATABASE_URL', f'sqlite:///{DATA}/tradeprism.db')
engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {}, pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

def now():
    return datetime.now(timezone.utc).timestamp()

class Candle(Base):
    __tablename__ = 'candles'
    id = Column(Integer, primary_key=True)
    symbol = Column(String(40), nullable=False)
    timeframe = Column(String(8), nullable=False)
    time = Column(Float, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    source = Column(String(30), nullable=False)
    fetched_at = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint('symbol', 'timeframe', 'time'),)

class Record(Base):
    """Append-only evidence, fills, exits, alerts and model metadata."""
    __tablename__ = 'records'
    id = Column(String(64), primary_key=True)
    kind = Column(String(30), nullable=False, index=True)
    owner = Column(String(80), nullable=False, index=True)
    symbol = Column(String(40), nullable=False, index=True)
    created = Column(Float, nullable=False)
    body = Column(Text, nullable=False)

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(String(64), primary_key=True)
    kind = Column(String(30), nullable=False)
    symbol = Column(String(40), nullable=False)
    timeframe = Column(String(8), nullable=False)
    status = Column(String(20), nullable=False, default='queued')
    created = Column(Float, nullable=False)
    updated = Column(Float, nullable=False)
    detail = Column(Text, nullable=False, default='Queued')

class Workspace(Base):
    __tablename__ = 'workspaces'
    key = Column(String(160), primary_key=True)
    body = Column(Text, nullable=False)
    updated = Column(Float, nullable=False)

def init():
    Base.metadata.create_all(engine)
    # Database-level immutability also prevents accidental code-path rewrites.
    with engine.begin() as c:
        if engine.dialect.name == 'sqlite':
            for op in ('UPDATE', 'DELETE'):
                c.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS records_no_{op.lower()} BEFORE {op} ON records BEGIN SELECT RAISE(ABORT, 'Records are immutable'); END")
        elif engine.dialect.name == 'postgresql':
            c.exec_driver_sql("CREATE OR REPLACE FUNCTION reject_record_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Records are immutable'; END; $$")
            c.exec_driver_sql('DROP TRIGGER IF EXISTS records_immutable ON records')
            c.exec_driver_sql('CREATE TRIGGER records_immutable BEFORE UPDATE OR DELETE ON records FOR EACH ROW EXECUTE FUNCTION reject_record_change()')

@contextmanager
def session():
    with Session() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
