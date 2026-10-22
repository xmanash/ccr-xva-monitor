from datetime import date

from ccr_xva.models.schemas import MemoryEpisode


def test_recall_uses_the_newest_snapshot(service):
    repo = service.repo
    older = MemoryEpisode(
        id="zzzz-later-alphabetically",
        counterparty_id="CP",
        netting_set_id="NS",
        as_of=date(2026, 10, 5),
        label="exposure",
        peak_pfe=1.0,
        calculation_id="older",
    )
    newer = MemoryEpisode(
        id="aaaa-earlier-alphabetically",
        counterparty_id="CP",
        netting_set_id="NS",
        as_of=date(2026, 10, 5),
        label="exposure",
        peak_pfe=937_827.75,
        calculation_id="newer",
    )
    repo.add_episode(older)
    repo.add_episode(newer)
    assert repo.list_episodes("CP")[-1].calculation_id == "newer"
