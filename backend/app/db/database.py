import logging
from collections.abc import Generator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(f"sqlite:///{settings.sqlite_path}", connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all() only creates tables that don't exist yet — it never
    alters an existing one. This is a single-file SQLite DB with no
    migration framework, so when a model gains a new (nullable) field, the
    already-existing table on disk needs that column added by hand or every
    query against it breaks. Additive only — never drops/renames a column,
    so existing data is untouched.
    """
    with engine.connect() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing_columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table.name})"))}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(engine.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"))
                conn.commit()
                logger.info("migrated: added %s.%s", table.name, column.name)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
