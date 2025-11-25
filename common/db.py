# encoding:utf-8

import threading
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, scoped_session

from config import conf


class Base(DeclarativeBase):
    pass


_engine = None
_SessionFactory = None
_scoped = None
_lock = threading.Lock()


def _ensure_engine():
    global _engine, _SessionFactory, _scoped
    if _engine is None:
        with _lock:
            if _engine is None:
                db_url = conf().get("db_url")
                if not db_url:
                    raise RuntimeError("db_url not configured in config.json")
                _engine = create_engine(db_url, pool_pre_ping=True, future=True)
                _SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
                _scoped = scoped_session(_SessionFactory)
                _scoped = scoped_session(_SessionFactory)


def get_session():
    _ensure_engine()
    return _scoped()


def init_db():
    _ensure_engine()
    from common.models import Base as ModelsBase
    ModelsBase.metadata.create_all(_engine)


