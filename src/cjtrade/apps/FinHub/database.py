from cjtrade.apps.FinHub.config import settings
from cjtrade.pkgs import paths
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

# In cjtrade's data directory: not beside the code, which in an installed
# package is site-packages, and not the working directory.
_DB_FILE = paths.data_dir() / "finhub" / "finhub.db"
_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
DEFAULT_SQLITE_URL = f"sqlite:///{_DB_FILE}"

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL or DEFAULT_SQLITE_URL

# check_same_thread is a SQLite-only argument; passing it to Postgres fails.
_connect_args = ({"check_same_thread": False}
                 if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {})

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=_connect_args)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite ignores ON DELETE CASCADE unless foreign keys are switched on."""
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
