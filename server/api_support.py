from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Any

from domain import DomainLoader, DomainRouter, QueryAnalyzer, QueryIntent
from domain.boundary import sec_on_miss
from valuator.models.factory import create_llm_client
from valuator.utils.time_utils import Measurement


async def build_query_analysis(
    query: str,
    model: str,
    *,
    as_of_utc: str | None = None,
    usage_writer: Any | None = None,
):
    effective_as_of_utc = as_of_utc or datetime.utcnow().isoformat() + "Z"
    measurement = Measurement.start()
    try:
        domain_index, modules = DomainLoader().load()
        router = DomainRouter(
            analyzer=QueryAnalyzer(
                client=create_llm_client(model=model),
                on_miss=sec_on_miss,
            ),
        )
        router.bind_usage_writer(usage_writer)
        try:
            _, analysis = await router.analyze(
                QueryIntent(query=query),
                domain_index,
                modules,
                as_of_utc=effective_as_of_utc,
            )
        except TypeError as exc:
            if "as_of_utc" not in str(exc):
                raise
            _, analysis = await router.analyze(
                QueryIntent(query=query),
                domain_index,
                modules,
            )
    except Exception as exc:
        write_diagnostic_record = getattr(usage_writer, "write_diagnostic_record", None)
        if callable(write_diagnostic_record):
            await asyncio.to_thread(
                write_diagnostic_record,
                category="analysis",
                method="query_analysis.analyze",
                status="failed",
                summary=str(exc),
                started_at=measurement.started_at,
                duration_ms=round(measurement.latency_seconds() * 1000.0, 3),
                input_payload={
                    "query": query,
                    "model": model,
                    "as_of_utc": effective_as_of_utc,
                },
                result_payload={"error": str(exc)},
                error=str(exc),
            )
        raise

    write_diagnostic_record = getattr(usage_writer, "write_diagnostic_record", None)
    if callable(write_diagnostic_record):
        await asyncio.to_thread(
            write_diagnostic_record,
            category="analysis",
            method="query_analysis.analyze",
            status="success",
            summary=(
                f"domains={len(analysis.domain_ids)} "
                f"units={len(analysis.units)} "
                f"requirements={len(analysis.requirements)}"
            ),
            started_at=measurement.started_at,
            duration_ms=round(measurement.latency_seconds() * 1000.0, 3),
            input_payload={
                "query": query,
                "model": model,
                "as_of_utc": effective_as_of_utc,
            },
            result_payload=asdict(analysis),
        )
    return analysis
