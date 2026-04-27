import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from config import get_settings
from logging_setup import setup_logging

setup_logging()
settings = get_settings()
logger = logging.getLogger(settings.logger)
DATABASE_URL = settings.database_url

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


@event.listens_for(engine, "handle_error")
def _log_db_error(exception_context):
    logger.exception("Ошибка БД: %s", exception_context.original_exception)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
