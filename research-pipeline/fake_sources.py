"""In-memory fake corpus with injectable failures. No network.

Every source is fictional. Two sources plant a conflict on the same statistic
(`wfh_share`) with different values and dates. Two agree (`hybrid_attrition`).
One source can be told to time out (`office-vacancy-2025`).
"""
import asyncio
import time
from dataclasses import dataclass, field


class SourceTimeout(Exception):
    """Raised when a source is flagged to time out."""

    error_category = "transient"


class UnknownSource(Exception):
    error_category = "invalid_input"


@dataclass(frozen=True)
class Source:
    source_id: str
    title: str
    topic: str  # topic key the coordinator tells subagents to use
    url: str
    publication_date: str  # ISO 8601
    # Fields below are noise a real fetch would return. The tool trims them.
    boilerplate: str
    passages: tuple[str, ...]


CORPUS: dict[str, Source] = {s.source_id: s for s in [
    Source(
        "wfh-research-2023", "Remote Work Tracker, Q4 2022 wave",
        "wfh_share",
        "https://fake-sources.example/wfh-research-2023", "2023-01-20",
        "Cookie banner. Subscribe to our newsletter. Related: 14 articles. " * 8,
        ("Across 2022, 28% of paid full days in the US were worked from home.",
         "Hybrid arrangements accounted for most of that share."),
    ),
    Source(
        "census-pulse-2025", "Household Pulse Survey, remote work module",
        "wfh_share",
        "https://fake-sources.example/census-pulse-2025", "2025-04-02",
        "Site navigation. Accessibility statement. Footer links. " * 8,
        ("In 2024, 22% of paid full days in the US were worked from home.",
         "The survey counts paid days only and excludes self-employed respondents."),
    ),
    Source(
        "hybrid-trial-2024", "Randomized hybrid trial at a 1,600-person firm",
        "hybrid_attrition",
        "https://fake-sources.example/hybrid-trial-2024", "2024-06-10",
        "Advertisement. Share on social media. Author bio. " * 8,
        ("Employees assigned to hybrid schedules quit 33% less often than the office group.",
         "Performance reviews and promotion rates did not differ between groups."),
    ),
    Source(
        "retention-review-2025", "Review of eleven hybrid retention studies",
        "hybrid_attrition",
        "https://fake-sources.example/retention-review-2025", "2025-02-14",
        "Citation export links. PDF download. Reprint permissions. " * 8,
        ("Pooled estimates show a 33% reduction in attrition under hybrid schedules.",
         "Effects were larger for junior staff."),
    ),
    Source(
        "office-vacancy-2025", "National office vacancy report",
        "office_vacancy",
        "https://fake-sources.example/office-vacancy-2025", "2025-08-30",
        "Subscriber paywall text. Broker contact forms. " * 8,
        ("US office vacancy reached 19.8% in mid-2025, a record in this series.",),
    ),
    Source(
        "lease-trends-2024", "Corporate lease renewal trends",
        "lease_footprint",
        "https://fake-sources.example/lease-trends-2024", "2024-11-05",
        "Related reports. Press contacts. Terms of use. " * 8,
        ("Median renewed lease footprint shrank 14% against the pre-2020 lease.",),
    ),
]}


@dataclass
class FakeSources:
    """Source access with failure flags and a call log for overlap measurement."""

    failures: dict[str, str] = field(default_factory=dict)  # source_id -> "timeout"
    latency_s: float = 2.0
    calls: list[dict] = field(default_factory=list)

    def catalog(self) -> list[dict]:
        return [{"source_id": s.source_id, "title": s.title, "topic": s.topic} for s in CORPUS.values()]

    async def fetch(self, source_id: str) -> dict:
        """Return only the fields the subagent needs, never the boilerplate."""
        entry = {"source_id": source_id, "start": time.monotonic(), "end": None}
        self.calls.append(entry)
        try:
            await asyncio.sleep(self.latency_s)
            if source_id not in CORPUS:
                raise UnknownSource(f"no source with id {source_id!r}")
            if self.failures.get(source_id) == "timeout":
                raise SourceTimeout(f"source {source_id} timed out after {self.latency_s}s")
            s = CORPUS[source_id]
            return {"source_id": s.source_id, "source_url": s.url,
                    "publication_date": s.publication_date, "passages": list(s.passages)}
        finally:
            entry["end"] = time.monotonic()

    def max_overlap(self) -> int:
        """Largest number of fetches in flight at the same instant."""
        events = sorted([(c["start"], 1) for c in self.calls]
                        + [(c["end"], -1) for c in self.calls if c["end"]])
        cur = best = 0
        for _, d in events:
            cur += d
            best = max(best, cur)
        return best
