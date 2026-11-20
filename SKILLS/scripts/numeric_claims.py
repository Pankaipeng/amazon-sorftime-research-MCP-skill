"""Verify numeric claims against product facts shared by copy and design."""

import re
from decimal import Decimal, ROUND_HALF_UP


NUMBER = r"\d+(?:\.\d+)?"
UNIT = r"inches\b|inch\b|in\b|cm\b|mm\b|\""
AXIS = r"wide\b|width\b|deep\b|depth\b|high\b|height\b|long\b|length\b|[wdhl]\b"
SIZE = re.compile(rf"\b({NUMBER})\s*({UNIT})(?:\s+({AXIS}))?", re.I)
TRIPLE = re.compile(
    rf"\b({NUMBER})\s*(?:({UNIT}))?\s*[×x]\s*"
    rf"({NUMBER})\s*(?:({UNIT}))?\s*[×x]\s*({NUMBER})\s*({UNIT})",
    re.I,
)
WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()
COUNT = r"\d+|" + "|".join(WORDS)
BOTTLES = re.compile(
    rf"\b({COUNT})(?:\s*[-‑]\s*|\s+)(?:(?:standard|red|wine)\s+)*bottles?\b",
    re.I,
)
PER_TIER = re.compile(rf"\b({COUNT})\s+per\s+(?:lower\s+)?(?:tier|row)\b", re.I)
TIER_SCOPE = re.compile(
    r"\b(?:per|each(?:\s+of\s+the)?)\s+(?:two\s+)?(?:lower\s+)?(?:tiers?|rows?)\b", re.I
)
TOP_SCOPE = re.compile(r"\b(?:top|upper)\s+(?:shelf|tier)\b", re.I)


def fact_at(facts, path):
    for key in path.split("."):
        if not isinstance(facts, dict):
            return None
        facts = facts.get(key)
    return facts


def dimension_matches(number, unit, expected_inches, expected_cm=None):
    number = Decimal(number)
    scale = {"cm": Decimal("2.54"), "mm": Decimal("25.4")}.get(unit.lower(), Decimal(1))
    expected = (Decimal(str(expected_cm)) * (10 if unit.lower() == "mm" else 1)
                if expected_cm is not None and unit.lower() in {"cm", "mm"}
                else Decimal(str(expected_inches)) * scale)
    return expected.quantize(Decimal(1).scaleb(number.as_tuple().exponent),
                             rounding=ROUND_HALF_UP) == number


def dimension_issues(text, facts):
    outer = fact_at(facts, "dims.outer_in")
    if not isinstance(outer, dict) or any(outer.get(axis) is None for axis in "lwh"):
        return []
    metric = fact_at(facts, "dims.outer_cm") or {}
    allowed = [(outer[axis], metric.get(axis)) for axis in "lwh"]
    diameter = fact_at(facts, "material.suction.dia_in")
    if diameter is not None:
        allowed.append((diameter, None))
    issues = []
    spans = []
    for found in TRIPLE.finditer(text):
        n1, u1, n2, u2, n3, unit = found.groups()
        spans.append(found.span())
        for axis, number, item_unit in zip("lwh", (n1, n2, n3), (u1, u2, unit)):
            if not dimension_matches(number, item_unit or unit, outer[axis], metric.get(axis)):
                issues.append(f"三围 {found[0]} 与事实卡 dims.outer_in.{axis}={outer[axis]} in 不一致")
    for found in SIZE.finditer(text):
        if any(start <= found.start() < end for start, end in spans):
            continue
        number, unit, label = found.groups()
        clause = re.split(r"[;!?\n]", text[:found.start()])[-1] + re.split(
            r"[;!?\n]", text[found.start():], maxsplit=1
        )[0]
        axes = fact_at(facts, "dims.outer_axes") or {}
        width_axis = "l" if re.search(r"\b(?:deep|depth|d)\b", clause, re.I) else "w"
        axis_map = {
            "wide": axes.get("width", width_axis), "width": axes.get("width", width_axis),
            "w": axes.get("width", width_axis), "deep": axes.get("depth", "w"),
            "depth": axes.get("depth", "w"), "d": axes.get("depth", "w"),
            "height": "h", "high": "h", "h": "h", "length": "l", "long": "l", "l": "l",
        }
        axis = axis_map.get((label or "").lower())
        expected = [(outer[axis], metric.get(axis))] if axis else allowed
        if not any(dimension_matches(number, unit, inches, cm) for inches, cm in expected):
            bound = f"dims.outer_in.{axis}={outer[axis]} in" if axis else "事实卡尺寸"
            issues.append(f"尺寸 {found[0]} 与 {bound} 不一致")
    return issues


def bottle_issues(text, facts):
    total = fact_at(facts, "structure.wine_bottles_lower")
    if total is None:
        total = fact_at(facts, "specs.standard_red_wine_bottles_lower_tiers")
    per_tier = fact_at(facts, "structure.wine_bottles_per_tier")
    upper = fact_at(facts, "structure.wine_bottles_top")
    if total is per_tier is upper is None and not re.search(r"\bwine\s+(?:rack|bottles?)\b", text, re.I):
        return []
    tier_count = fact_at(facts, "specs.bottle_tiers")
    if per_tier is None and isinstance(total, int) and isinstance(tier_count, int) and tier_count > 0 and total % tier_count == 0:
        per_tier = total // tier_count
    issues = []
    for clause in re.split(r"[,;!?\n]|\.(?!\d)", text):
        claims = [(m, per_tier, "单层") for m in PER_TIER.finditer(clause)]
        for match in BOTTLES.finditer(clause):
            tail = clause[match.end():]
            if TIER_SCOPE.search(tail):
                claims.append((match, per_tier, "单层"))
            elif (re.search(r"\b(?:on|in)\s+(?:the\s+)?(?:top|upper)\s+(?:shelf|tier)\b", tail, re.I)
                  or (TOP_SCOPE.search(clause[:match.start()]) and not re.search(r"\blower\b", tail, re.I))):
                claims.append((match, upper, "顶层"))
            else:
                claims.append((match, total, "下方容量"))
        for match, expected, scope in claims:
            count = match[1].lower()
            value = int(count) if count.isdigit() else WORDS.index(count)
            if value != expected:
                bound = "未确认" if expected is None else f"{expected} 瓶"
                issues.append(f"{scope}主张 {match[0]} 与事实卡（{bound}）不一致")
    return issues
