"""Book the portfolio and run the deterministic exposure and XVA engines."""

from __future__ import annotations

from datetime import date

from ccr_xva.engines.exposure import simulate_exposure
from ccr_xva.engines.xva import xva_from_profile
from ccr_xva.memory.repository import Repository
from ccr_xva.memory.tracing import build_trace, export_langfuse
from ccr_xva.models.schemas import CSA, Counterparty, ExposureProfile, MarketScenario, MemoryEpisode, Trade, XVAResult
from ccr_xva.rag.ingest import load_markdown_chunks
from ccr_xva.rag.pinecone_store import PineconeCorpus, PineconeSettings
from ccr_xva.rag.retriever import build_retriever
from shared.ids import new_id
from shared.settings import Settings, get_settings


class RiskService:
    def __init__(self, repo: Repository, settings: Settings | None = None):
        self.repo = repo
        self.settings = settings or get_settings()
        self._retriever = None

    def ensure_corpus(self):
        chunks = self.repo.list_chunks()
        if not chunks:
            chunks = load_markdown_chunks()
            if chunks:
                self.repo.replace_chunks(chunks)
        if self._retriever is None:
            pinecone = _pinecone_corpus(self.settings)
            self._retriever = build_retriever(
                chunks,
                chroma_path=None if pinecone is not None else self.settings.chroma_path,
                pinecone=pinecone,
            )
        return self._retriever

    def resolve_scenario(self, scenario: MarketScenario | None) -> MarketScenario:
        return scenario or MarketScenario(as_of=date.today())

    def netting_sets_for(self, counterparty_id: str) -> list[str]:
        return sorted({trade.netting_set_id for trade in self.repo.list_trades() if trade.counterparty_id == counterparty_id})

    def find_counterparty(self, text: str) -> Counterparty | None:
        lowered = text.lower()
        matches = []
        for counterparty in self.repo.list_counterparties():
            name_hit = len(counterparty.name) >= 3 and counterparty.name.lower() in lowered
            id_hit = len(counterparty.id) >= 3 and counterparty.id.lower() in lowered.split()
            if name_hit or id_hit:
                matches.append(counterparty)
        if not matches:
            return None
        return max(matches, key=lambda item: len(item.name))

    def calculate_exposure(
        self,
        netting_set_id: str,
        scenario: MarketScenario | None = None,
        csa_override: CSA | None = None,
        save_latest: bool = True,
        label: str = "exposure",
    ) -> ExposureProfile:
        scenario = self.resolve_scenario(scenario)
        trades = self.repo.list_trades(netting_set_id)
        if not trades:
            raise ValueError(
                f"No trades are stored for netting set {netting_set_id}. "
                "Upload a trade file or load the sample book before calculating."
            )
        csa = csa_override if csa_override is not None else self.repo.get_csa(netting_set_id)
        use_collateral = csa is not None and any(trade.collateralized for trade in trades)
        raw = simulate_exposure(trades, scenario, csa=csa, collateralized=use_collateral)
        profile = ExposureProfile(
            netting_set_id=netting_set_id,
            dates=raw["dates"],
            ee=raw["ee"],
            pfe_95=raw["pfe_95"],
            pfe_99=raw["pfe_99"],
            ene=raw["ene"],
            epe=raw["epe"],
            effective_epe=raw["effective_epe"],
            calculation_id=new_id(),
            drivers=raw["drivers"],
        )
        self.repo.save_exposure(profile, latest=save_latest)
        counterparty_id = trades[0].counterparty_id
        self.repo.add_episode(
            MemoryEpisode(
                id=new_id(),
                counterparty_id=counterparty_id,
                netting_set_id=netting_set_id,
                as_of=scenario.as_of,
                label=label,
                peak_pfe=raw["peak_pfe_95"],
                calculation_id=profile.calculation_id,
                summary=f"Peak PFE95 {raw['peak_pfe_95']:.2f}",
            )
        )
        trace = build_trace(
            profile.calculation_id,
            "exposure",
            {
                "netting_set_id": netting_set_id,
                "scenario": scenario.model_dump(mode="json"),
                "trade_ids": [trade.trade_id for trade in trades],
                "csa": None if csa is None else csa.model_dump(mode="json"),
            },
            {"epe": profile.epe, "effective_epe": profile.effective_epe, "peak_pfe_95": raw["peak_pfe_95"]},
            [
                f"Loaded {len(trades)} trades",
                f"Simulated {raw['n_paths']} antithetic paths",
                "Applied cash CSA" if use_collateral else "No CSA applied",
                "Aggregated EE, PFE95, and PFE99",
            ],
        )
        self.repo.save_trace(trace)
        export_langfuse(trace, self.settings)
        return profile

    def calculate_xva(
        self,
        netting_set_id: str,
        scenario: MarketScenario | None = None,
        profile: ExposureProfile | None = None,
        recovery: float | None = None,
        pd: float | None = None,
        save_latest: bool = True,
        csa_override: CSA | None = None,
    ) -> XVAResult:
        scenario = self.resolve_scenario(scenario)
        trades = self.repo.list_trades(netting_set_id)
        if not trades:
            raise ValueError(
                f"No trades are stored for netting set {netting_set_id}. "
                "Upload a trade file or load the sample book before calculating."
            )
        counterparty = self.repo.get_counterparty(trades[0].counterparty_id)
        if profile is None:
            profile = self.calculate_exposure(
                netting_set_id,
                scenario,
                csa_override=csa_override,
                save_latest=save_latest,
                label="exposure",
            )
        pd_1y = pd if pd is not None else (counterparty.pd if counterparty else None)
        if pd_1y is None:
            raise ValueError("Counterparty PD is required before CVA can be calculated")
        recovery_rate = recovery if recovery is not None else (counterparty.recovery_rate if counterparty else 0.40)
        numbers = xva_from_profile(profile, scenario, pd_1y, recovery_rate)
        result = XVAResult(
            netting_set_id=netting_set_id,
            cva=numbers["cva"],
            dva=numbers["dva"],
            fva=numbers["fva"],
            total_xva=numbers["total_xva"],
            assumptions={
                "pd": pd_1y,
                "recovery_rate": recovery_rate,
                "own_pd": scenario.own_pd,
                "own_recovery": scenario.own_recovery,
                "funding_spread": scenario.funding_spread,
                "usd_rate": scenario.usd_rate,
                "hw_a": scenario.hw_a,
                "hw_sigma": scenario.hw_sigma,
                "n_paths": scenario.n_paths,
                "seed": scenario.seed,
                "exposure_calculation_id": profile.calculation_id,
                "model": "hull-white-irs + gbm-fx-forward; unilateral CVA bucket sum",
            },
            calculation_id=new_id(),
        )
        self.repo.save_xva(result, latest=save_latest)
        self.repo.add_episode(
            MemoryEpisode(
                id=new_id(),
                counterparty_id=trades[0].counterparty_id,
                netting_set_id=netting_set_id,
                as_of=scenario.as_of,
                label="xva" if save_latest else "what-if",
                peak_pfe=max(profile.pfe_95) if profile.pfe_95 else None,
                cva=result.cva,
                calculation_id=result.calculation_id,
                summary=f"CVA {result.cva:.2f}",
            )
        )
        trace = build_trace(
            result.calculation_id,
            "xva",
            {"netting_set_id": netting_set_id, "assumptions": result.assumptions},
            result.model_dump(mode="json"),
            [
                f"Used exposure {profile.calculation_id}",
                "Computed unilateral CVA, DVA, and teaching FVA",
            ],
        )
        self.repo.save_trace(trace)
        export_langfuse(trace, self.settings)
        return result

    def what_if(
        self,
        netting_set_id: str,
        scenario: MarketScenario | None = None,
        threshold: float | None = None,
        threshold_delta: float | None = None,
        recovery: float | None = None,
        pd: float | None = None,
    ) -> dict:
        scenario = self.resolve_scenario(scenario)
        base_xva = self.calculate_xva(netting_set_id, scenario, save_latest=True)
        csa = self.repo.get_csa(netting_set_id)
        override = None
        if csa is not None and (threshold is not None or threshold_delta is not None):
            updated = threshold if threshold is not None else csa.threshold + float(threshold_delta or 0.0)
            override = csa.model_copy(update={"threshold": updated})
        elif threshold is not None or threshold_delta is not None:
            current = 0.0 if threshold_delta is None else 0.0
            updated = threshold if threshold is not None else current + float(threshold_delta or 0.0)
            override = CSA(csa_id=f"SHOCK-{netting_set_id}", netting_set_id=netting_set_id, threshold=updated)
        shocked = self.calculate_xva(
            netting_set_id,
            scenario,
            recovery=recovery,
            pd=pd,
            save_latest=False,
            csa_override=override,
        )
        return {"base": base_xva, "shocked": shocked, "threshold": None if override is None else override.threshold}

    def sensitivity(self, netting_set_id: str, scenario: MarketScenario | None = None, relative_vol_bump: float = 0.10) -> dict:
        scenario = self.resolve_scenario(scenario)
        base = self.calculate_xva(netting_set_id, scenario, save_latest=True)
        shocked_scenario = scenario.model_copy(
            update={
                "hw_sigma": scenario.hw_sigma * (1.0 + relative_vol_bump),
                "fx_vols": {key: value * (1.0 + relative_vol_bump) for key, value in scenario.fx_vols.items()},
            }
        )
        shocked = self.calculate_xva(netting_set_id, shocked_scenario, save_latest=False)
        return {"base": base, "shocked": shocked, "relative_vol_bump": relative_vol_bump}

    def load_sample_book(self) -> dict:
        """Load the synthetic IRS and FX book. An existing CSA on a netting set is left in place."""
        from ccr_xva.synthetic.portfolio import build_portfolio

        counterparties, trades, csas = build_portfolio(n_counterparties=4, as_of=date(2026, 10, 5), seed=7)
        for counterparty in counterparties:
            self.store_counterparty(counterparty)
        for trade in trades:
            self.store_trade(trade)
        for csa in csas:
            if self.repo.get_csa(csa.netting_set_id) is None:
                self.store_csa(csa)
        return {
            "trades": len(trades),
            "counterparties": len(counterparties),
            "netting_sets": sorted({trade.netting_set_id for trade in trades}),
        }

    def store_counterparty(self, counterparty: Counterparty) -> Counterparty:
        return self.repo.upsert_counterparty(counterparty)

    def store_trade(self, trade: Trade) -> Trade:
        if self.repo.get_counterparty(trade.counterparty_id) is None:
            self.repo.upsert_counterparty(
                Counterparty(id=trade.counterparty_id, name=trade.counterparty_id, pd=0.01, recovery_rate=0.40)
            )
        return self.repo.upsert_trade(trade)

    def store_csa(self, csa: CSA) -> CSA:
        fraction = csa.metadata.get("mta_fraction")
        if fraction is not None and csa.mta == 0.0:
            notional = sum(trade.notional for trade in self.repo.list_trades(csa.netting_set_id))
            if notional:
                csa = csa.model_copy(update={"mta": fraction * notional})
        return self.repo.upsert_csa(csa)


def _pinecone_corpus(settings: Settings) -> PineconeCorpus | None:
    key = (settings.pinecone_api_key or "").strip()
    if not key:
        return None
    return PineconeCorpus(
        PineconeSettings(
            api_key=key,
            index=settings.pinecone_index,
            cloud=settings.pinecone_cloud,
            region=settings.pinecone_region,
            model=settings.pinecone_embed_model,
            namespace=settings.pinecone_namespace,
        )
    )


def exposure_chart(profile: ExposureProfile) -> dict:
    dates = [day.isoformat() if isinstance(day, date) else str(day) for day in profile.dates]
    return {
        "data": [
            {"type": "scatter", "mode": "lines", "name": "EE", "x": dates, "y": profile.ee},
            {"type": "scatter", "mode": "lines", "name": "PFE95", "x": dates, "y": profile.pfe_95},
            {"type": "scatter", "mode": "lines", "name": "PFE99", "x": dates, "y": profile.pfe_99},
        ],
        "layout": {
            "title": f"Exposure for {profile.netting_set_id}",
            "xaxis": {"title": "Date"},
            "yaxis": {"title": "USD"},
        },
    }

