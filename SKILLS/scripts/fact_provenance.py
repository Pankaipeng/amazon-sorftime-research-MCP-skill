"""Provenance checks shared by the fact-card and copy gates."""

import re


def outer_dimensions_from_packaging(facts):
    """Detect legacy fact cards that explicitly used package dimensions as a fallback."""
    detail = (facts.get("_source_detail") or {}).get("dims.outer_in")
    return isinstance(detail, str) and bool(
        re.search(r"(?:用|取自|来自|按)包装(?:外?尺寸|规格)", detail)
    )
