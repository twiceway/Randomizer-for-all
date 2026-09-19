"""MSB / spawn template_id normalization (Python · mirrors MsbEnemyPoc NormalizeTemplateId)."""

from __future__ import annotations


def normalize_template_id(template_id: str | None) -> str | None:
    if not template_id:
        return None
    low = template_id.lower()
    idx = low.find("|demount")
    if idx >= 0:
        return template_id[:idx]
    return template_id
