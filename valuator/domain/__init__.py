from __future__ import annotations

from importlib import import_module

from .company import Company, find_company
from .query import (
    QueryAnalysis,
    QueryBreakdown,
    QueryEntity,
    QueryIntent,
    QueryRelation,
    QueryRequirement,
    QueryStep,
    QueryUnit,
    build_query_breakdown,
    fill_routing_defaults,
)

__all__ = [
    "AcceptanceCheck",
    "Company",
    "DomainIndex",
    "DomainLoader",
    "DomainModule",
    "DomainModuleContext",
    "DomainRouter",
    "QueryBreakdown",
    "QueryEntity",
    "QueryAnalysis",
    "QueryAnalyzer",
    "QueryIntent",
    "QueryRelation",
    "QueryRequirement",
    "QueryStep",
    "QueryUnit",
    "RubricAspect",
    "expand",
    "analyze_query",
    "build_query_breakdown",
    "fill_routing_defaults",
    "find_company",
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
