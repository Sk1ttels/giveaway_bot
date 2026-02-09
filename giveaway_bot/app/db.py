import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Load .env reliably both locally and on server
BASE_DIR = Path(__file__).resolve().parents[1]  # .../giveaway_bot
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH if ENV_PATH.exists() else None)

def _default_sqlite_url() -> str:
    db_file = BASE_DIR / "giveaway.sqlite3"
    # SQLAlchemy expects sqlite:///C:/path on Windows and sqlite:////abs/path on Linux/mac
    p = db_file.resolve()
    return f"sqlite:///{p.as_posix()}"

DB_URL = os.getenv("DB_URL", "").strip() or _default_sqlite_url()

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass
