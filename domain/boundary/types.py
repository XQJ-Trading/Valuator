from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.company import Listing


@dataclass(frozen=True, slots=True)
class ListingSeed:
    company_id: str
    company_name: str
    company_aliases: tuple[str, ...]
    listing: "Listing"
