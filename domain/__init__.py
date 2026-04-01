from __future__ import annotations

from importlib import import_module

from .company import (
    Company,
    CompanySurfaceResolution,
    Listing,
    ListingSeed,
    Subject,
    resolve_company_surfaces,
    resolve_subjects,
)
from .query import (
    QueryAnalysis,
    QueryBreakdown,
    QueryEntity,
    QueryIntent,
    QueryRelation,
    QueryRequirement,
    QueryStep,
    TemporalContract,
    QueryUnit,
    build_query_breakdown,
    fill_routing_defaults,
    summarize_temporal_contract,
)

__all__ = [
    "AcceptanceCheck",
    "Company",
    "CompanySurfaceResolution",
    "DomainIndex",
    "DomainLoader",
    "DomainModule",
    "DomainModuleContext",
    "DomainRouter",
    "Listing",
    "ListingSeed",
    "QueryBreakdown",
    "QueryEntity",
    "QueryAnalysis",
    "QueryAnalyzer",
    "QueryIntent",
    "QueryRelation",
    "QueryRequirement",
    "QueryStep",
    "TemporalContract",
    "QueryUnit",
    "RubricAspect",
    "Subject",
    "expand",
    "analyze_query",
    "build_query_breakdown",
    "fill_routing_defaults",
    "resolve_company_surfaces",
    "resolve_subjects",
    "summarize_temporal_contract",
]

_LAZY_EXPORTS = {
    "AcceptanceCheck": (".types", "AcceptanceCheck"),
    "DomainIndex": (".types", "DomainIndex"),
    "DomainLoader": (".loader", "DomainLoader"),
    "DomainModule": (".types", "DomainModule"),
    "DomainModuleContext": (".types", "DomainModuleContext"),
    "DomainRouter": (".router", "DomainRouter"),
    "QueryAnalyzer": (".query_analysis", "QueryAnalyzer"),
    "RubricAspect": (".types", "RubricAspect"),
    "expand": (".expander", "expand"),
    "analyze_query": (".router", "analyze_query"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
