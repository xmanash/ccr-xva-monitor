"""Load and store books, calculations, and entity memory."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from ccr_xva.memory.db import (
    CSARow,
    ChunkRow,
    CounterpartyRow,
    EpisodeRow,
    ExposureRow,
    MessageRow,
    SessionRow,
    TraceRow,
    TradeRow,
    XVARow,
    make_session_factory,
)
from ccr_xva.models.schemas import (
    CSA,
    CalculationTrace,
    Counterparty,
    ExposureProfile,
    MemoryEpisode,
    Trade,
    XVAResult,
)
from shared.ids import new_id

_FACTORIES: dict[str, object] = {}


def get_repository(database_url: str) -> "Repository":
    factory = _FACTORIES.get(database_url)
    if factory is None:
        factory = Repository(database_url)
        _FACTORIES[database_url] = factory
    return factory


def clear_repository_cache() -> None:
    _FACTORIES.clear()


class Repository:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._session_factory = make_session_factory(database_url)

    def _session(self):
        return self._session_factory()

    def upsert_counterparty(self, counterparty: Counterparty) -> Counterparty:
        payload = counterparty.model_dump_json()
        with self._session() as session:
            row = session.get(CounterpartyRow, counterparty.id)
            if row is None:
                session.add(CounterpartyRow(id=counterparty.id, payload=payload))
            else:
                row.payload = payload
            session.commit()
        return counterparty

    def get_counterparty(self, counterparty_id: str) -> Counterparty | None:
        with self._session() as session:
            row = session.get(CounterpartyRow, counterparty_id)
            return Counterparty.model_validate_json(row.payload) if row else None

    def list_counterparties(self) -> list[Counterparty]:
        with self._session() as session:
            rows = session.scalars(select(CounterpartyRow)).all()
            return [Counterparty.model_validate_json(row.payload) for row in rows]

    def upsert_trade(self, trade: Trade) -> Trade:
        payload = trade.model_dump_json()
        with self._session() as session:
            row = session.get(TradeRow, trade.trade_id)
            if row is None:
                session.add(
                    TradeRow(
                        trade_id=trade.trade_id,
                        counterparty_id=trade.counterparty_id,
                        netting_set_id=trade.netting_set_id,
                        payload=payload,
                    )
                )
            else:
                row.counterparty_id = trade.counterparty_id
                row.netting_set_id = trade.netting_set_id
                row.payload = payload
            session.commit()
        return trade

    def list_trades(self, netting_set_id: str | None = None) -> list[Trade]:
        with self._session() as session:
            stmt = select(TradeRow)
            if netting_set_id is not None:
                stmt = stmt.where(TradeRow.netting_set_id == netting_set_id)
            rows = session.scalars(stmt).all()
            return [Trade.model_validate_json(row.payload) for row in rows]

    def upsert_csa(self, csa: CSA) -> CSA:
        payload = csa.model_dump_json()
        with self._session() as session:
            existing = session.scalars(select(CSARow).where(CSARow.netting_set_id == csa.netting_set_id)).all()
            for row in existing:
                if row.csa_id != csa.csa_id:
                    session.delete(row)
            row = session.get(CSARow, csa.csa_id)
            if row is None:
                session.add(CSARow(csa_id=csa.csa_id, netting_set_id=csa.netting_set_id, payload=payload))
            else:
                row.netting_set_id = csa.netting_set_id
                row.payload = payload
            session.commit()
        return csa

    def get_csa(self, netting_set_id: str) -> CSA | None:
        with self._session() as session:
            row = session.scalars(select(CSARow).where(CSARow.netting_set_id == netting_set_id)).first()
            return CSA.model_validate_json(row.payload) if row else None

    def save_exposure(self, profile: ExposureProfile, latest: bool = True) -> ExposureProfile:
        payload = profile.model_dump_json()
        with self._session() as session:
            if latest:
                current = session.scalars(
                    select(ExposureRow).where(ExposureRow.netting_set_id == profile.netting_set_id)
                ).all()
                for row in current:
                    row.is_latest = "0"
            session.merge(
                ExposureRow(
                    calculation_id=profile.calculation_id,
                    netting_set_id=profile.netting_set_id,
                    is_latest="1" if latest else "0",
                    payload=payload,
                )
            )
            session.commit()
        return profile

    def latest_exposure(self, netting_set_id: str) -> ExposureProfile | None:
        with self._session() as session:
            row = session.scalars(
                select(ExposureRow).where(
                    ExposureRow.netting_set_id == netting_set_id,
                    ExposureRow.is_latest == "1",
                )
            ).first()
            return ExposureProfile.model_validate_json(row.payload) if row else None

    def save_xva(self, result: XVAResult, latest: bool = True) -> XVAResult:
        payload = result.model_dump_json()
        with self._session() as session:
            if latest:
                current = session.scalars(select(XVARow).where(XVARow.netting_set_id == result.netting_set_id)).all()
                for row in current:
                    row.is_latest = "0"
            session.merge(
                XVARow(
                    calculation_id=result.calculation_id,
                    netting_set_id=result.netting_set_id,
                    is_latest="1" if latest else "0",
                    payload=payload,
                )
            )
            session.commit()
        return result

    def latest_xva(self, netting_set_id: str) -> XVAResult | None:
        with self._session() as session:
            row = session.scalars(
                select(XVARow).where(XVARow.netting_set_id == netting_set_id, XVARow.is_latest == "1")
            ).first()
            return XVAResult.model_validate_json(row.payload) if row else None

    def save_trace(self, trace: CalculationTrace) -> CalculationTrace:
        with self._session() as session:
            session.merge(
                TraceRow(
                    calculation_id=trace.calculation_id,
                    kind=trace.kind,
                    payload=trace.model_dump_json(),
                )
            )
            session.commit()
        return trace

    def list_traces(self, limit: int = 20) -> list[CalculationTrace]:
        with self._session() as session:
            rows = session.scalars(select(TraceRow)).all()
            traces = [CalculationTrace.model_validate_json(row.payload) for row in rows]
        traces.sort(key=lambda item: item.created_at)
        return traces[-limit:]

    def get_trace(self, calculation_id: str) -> CalculationTrace | None:
        with self._session() as session:
            row = session.get(TraceRow, calculation_id)
            return CalculationTrace.model_validate_json(row.payload) if row else None

    def add_episode(self, episode: MemoryEpisode) -> MemoryEpisode:
        with self._session() as session:
            session.merge(
                EpisodeRow(
                    id=episode.id,
                    counterparty_id=episode.counterparty_id,
                    netting_set_id=episode.netting_set_id,
                    as_of=episode.as_of.isoformat(),
                    peak_pfe=episode.peak_pfe,
                    cva=episode.cva,
                    payload=episode.model_dump_json(),
                )
            )
            session.commit()
        return episode

    def list_episodes(self, counterparty_id: str | None = None) -> list[MemoryEpisode]:
        with self._session() as session:
            stmt = select(EpisodeRow)
            if counterparty_id is not None:
                stmt = stmt.where(EpisodeRow.counterparty_id == counterparty_id)
            rows = session.scalars(stmt).all()
            episodes = [MemoryEpisode.model_validate_json(row.payload) for row in rows]
            return sorted(episodes, key=lambda item: (item.as_of, item.id))

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._session() as session:
            session.add(
                MessageRow(
                    id=new_id(),
                    session_id=session_id,
                    role=role,
                    content=content,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            session.commit()

    def recent_messages(self, session_id: str, limit: int = 8) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(select(MessageRow).where(MessageRow.session_id == session_id)).all()
            rows = sorted(rows, key=lambda row: row.created_at)[-limit:]
            return [{"role": row.role, "content": row.content} for row in rows]

    def set_focus(self, session_id: str, netting_set_id: str | None, counterparty_id: str | None) -> None:
        with self._session() as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                session.add(
                    SessionRow(
                        session_id=session_id,
                        netting_set_id=netting_set_id,
                        counterparty_id=counterparty_id,
                    )
                )
            else:
                row.netting_set_id = netting_set_id
                row.counterparty_id = counterparty_id
            session.commit()

    def get_focus(self, session_id: str) -> tuple[str | None, str | None]:
        with self._session() as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                return None, None
            return row.netting_set_id, row.counterparty_id

    def replace_chunks(self, chunks: list[dict]) -> None:
        with self._session() as session:
            for row in session.scalars(select(ChunkRow)).all():
                session.delete(row)
            for chunk in chunks:
                session.add(ChunkRow(id=chunk["id"], source=chunk["source"], text=chunk["text"]))
            session.commit()

    def list_chunks(self) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(select(ChunkRow)).all()
            return [{"id": row.id, "source": row.source, "text": row.text} for row in rows]


def dump_json(payload: dict) -> str:
    return json.dumps(payload)
