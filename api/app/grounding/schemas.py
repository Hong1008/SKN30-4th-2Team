"""Grounding API DTO."""

from pydantic import BaseModel


class GroundingCategory(BaseModel):
    code: str
    label: str


class GroundingItem(BaseModel):
    source_id: str
    law_name: str | None = None
    article: str | None = None
    text: str
    source: str | None = None
    source_url: str | None = None


class GroundingResponse(BaseModel):
    grounding_status: str
    category: GroundingCategory
    contract_type: str
    items: list[GroundingItem]
    message: str | None = None
