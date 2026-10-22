"""SQLite tables for books, results, memory, and traces."""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class CounterpartyRow(Base):
    __tablename__ = "counterparties"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class TradeRow(Base):
    __tablename__ = "trades"
    trade_id: Mapped[str] = mapped_column(String, primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String, index=True)
    netting_set_id: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[str] = mapped_column(Text)


class CSARow(Base):
    __tablename__ = "csas"
    csa_id: Mapped[str] = mapped_column(String, primary_key=True)
    netting_set_id: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[str] = mapped_column(Text)


class ExposureRow(Base):
    __tablename__ = "exposures"
    calculation_id: Mapped[str] = mapped_column(String, primary_key=True)
    netting_set_id: Mapped[str] = mapped_column(String, index=True)
    is_latest: Mapped[str] = mapped_column(String, default="0")
    payload: Mapped[str] = mapped_column(Text)


class XVARow(Base):
    __tablename__ = "xva_results"
    calculation_id: Mapped[str] = mapped_column(String, primary_key=True)
    netting_set_id: Mapped[str] = mapped_column(String, index=True)
    is_latest: Mapped[str] = mapped_column(String, default="0")
    payload: Mapped[str] = mapped_column(Text)


class TraceRow(Base):
    __tablename__ = "traces"
    calculation_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)


class EpisodeRow(Base):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String, index=True)
    netting_set_id: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[str] = mapped_column(String)
    peak_pfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    cva: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[str] = mapped_column(Text)


class MessageRow(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class SessionRow(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    netting_set_id: Mapped[str | None] = mapped_column(String, nullable=True)
    counterparty_id: Mapped[str | None] = mapped_column(String, nullable=True)


class ChunkRow(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def make_session_factory(database_url: str):
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
