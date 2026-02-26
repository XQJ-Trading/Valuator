from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

RequirementType = str


class RequirementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    unit_id: int
    requirement_type: RequirementType
    acceptance: str
    required: bool = True


class PlanContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RequirementItem] = Field(default_factory=list)
    rationale: str = ""


def evaluate_contract(contract: PlanContract | None, markdown: str) -> list[str]:
    if contract is None:
        return []
    text = markdown or ""
    missing: list[str] = []
    for item in contract.items:
        if not item.required:
            continue
        marker = f"[{item.id}]"
        if marker not in text:
            missing.append(item.id)
    return missing
