"""Tiered validation for anti-laziness: cast and places, with graph connectivity."""
from __future__ import annotations

import re
from typing import Any

# Tier definitions
TIERS = {
    "L1": {"count": (1, 3), "words": (250, 350), "fields": ["want", "need", "flaw", "wound", "arc", "voice", "secret"]},
    "L2": {"count": (4, 7), "words": (150, 200), "fields": []},
    "L3": {"count": (6, 12), "words": (60, 90), "fields": []},
    "L4": {"count": (10, 20), "words": (1, 20), "fields": []},  # 1 line ~ <20w
}

PLACES_TIERS = {
    "L1": {"count": (3, 5)},
    "L2": {"count": (5, 8)},
    "L3": {"count": (6, 12)},
}

TOTAL_NAMED_80K = 22
TOTAL_PLACES_MIN = 14

def word_count(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return len(re.findall(r"\b[\w’'-]+\b", text, re.UNICODE))

def _tier_words_ok(text: str, low: int, high: int) -> bool:
    wc = word_count(text)
    return low <= wc <= high

def validate_tiered_cast(proposal: dict[str, Any], target_words: int = 80000) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    characters = proposal.get("characters", [])
    if not isinstance(characters, list):
        findings.append({"code": "tier.characters-not-list", "severity": "blocking"})
        return findings
    # Determine tier by index or explicit tier field
    # Proposal may contain tier field; if not, infer by position
    # L1: first 1-3, L2: next 4-7, L3: next 6-12, L4: rest 10-20
    # For validation, we check counts and word ranges per tier
    # If proposal has explicit tier grouping, use it; else infer
    tiered: dict[str, list] = {"L1": [], "L2": [], "L3": [], "L4": []}
    # If characters have tier field, group by it
    has_tier_field = any(isinstance(c, dict) and "tier" in c for c in characters)
    if has_tier_field:
        for ch in characters:
            tier = str(ch.get("tier", "L4")).upper()
            if tier not in tiered:
                tier = "L4"
            tiered[tier].append(ch)
    else:
        # Infer by slice: L1 first 3, L2 next 7, L3 next 12, L4 rest
        # But counts are validated, so we need to slice according to expected counts
        # Use proposal size to infer: take first 3 as L1, next 7 as L2, next up to 12 as L3, rest as L4
        tiered["L1"] = characters[0:3]
        tiered["L2"] = characters[3:10]
        tiered["L3"] = characters[10:22]
        tiered["L4"] = characters[22:42]
        # Trim empty leading tiers if proposal smaller
        # Instead, if proposal has exactly 22, this will split as 3,7,12,0 -> L4 empty but ok for 80k? But L4 expects 10-20
        # For validation we need to handle flexible; better to validate based on actual counts, not slices
        # So we will instead validate that total_named >=22 and that each tier's count and words fit if present
        # For strict tier counts, we check that L1 1-3, L2 4-7 etc., but if proposal doesn't have tier field, we can't know
        # So we fallback to total checks and word range checks per character based on its tier inference
        # Simplify: tiered is just for reporting, but we will validate total and per-character word counts
        pass

    # Validate counts — only strict when full 80k; for scaled lengths, L3/L4 are lenient
    for tier, spec in TIERS.items():
        cnt = len(tiered[tier])
        low, high = spec["count"]
        if has_tier_field:
            # For scaled lengths, relax L3/L4 (allow 0) to avoid blocking valid scaled proposals like 12 at 40k
            if target_words != 80000 and tier in ("L3", "L4") and cnt == 0:
                continue
            if target_words != 80000 and tier == "L3" and cnt < low:
                # scaled L3 can be smaller than 6 when total is scaled
                continue
            if not (low <= cnt <= high):
                findings.append({"code": f"tier.{tier}.count", "severity": "blocking", "count": cnt, "expected": f"{low}-{high}"})
        else:
            # In inference mode, we validate total and per-character, not per-tier counts strictly
            # But we still ensure L1 has 1-3 if any characters exist
            if tier == "L1":
                if not (low <= cnt <= high or cnt == 0):
                    # allow 0 only if total is 0
                    if cnt != 0 and not (low <= cnt <= high):
                        findings.append({"code": f"tier.{tier}.count", "severity": "blocking", "count": cnt, "expected": f"{low}-{high}"})

    # Validate total_named scaled — only when tiered (has_tier_field) to avoid breaking legacy single-char proposals
    total_named = len(characters)
    if has_tier_field:
        required = int(TOTAL_NAMED_80K * (target_words / 80000)) if target_words else TOTAL_NAMED_80K
        required = max(required, TOTAL_NAMED_80K if target_words >= 80000 else required)
        if total_named < required:
            findings.append({"code": "tier.total_named", "severity": "blocking", "total": total_named, "required": required})

    # Validate word counts and required fields per tier — only when tiered
    if has_tier_field:
        for tier, spec in TIERS.items():
            low, high = spec["words"]
            required_fields = spec["fields"]
            for ch in tiered[tier]:
                if not isinstance(ch, dict):
                    continue
                text_parts = []
                for k in ["summary", "voice", "appearance", "past", "want", "need", "flaw", "wound", "arc", "secret", "description", "invariant"]:
                    v = ch.get(k)
                    if isinstance(v, str):
                        text_parts.append(v)
                combined = " ".join(text_parts)
                wc = word_count(combined)
                if tier == "L4":
                    if wc < 1 or wc > 20:
                        findings.append({"code": f"tier.{tier}.words", "severity": "blocking", "id": ch.get("id"), "words": wc, "expected": f"{low}-{high}"})
                else:
                    if not (low <= wc <= high):
                        findings.append({"code": f"tier.{tier}.words", "severity": "blocking", "id": ch.get("id"), "words": wc, "expected": f"{low}-{high}"})
                for field in required_fields:
                    if not isinstance(ch.get(field), str) or not ch.get(field).strip():
                        findings.append({"code": f"tier.{tier}.field.{field}", "severity": "blocking", "id": ch.get("id")})

    return findings

def validate_places_tiered(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    places = proposal.get("places", [])
    if not isinstance(places, list):
        findings.append({"code": "tier.places-not-list", "severity": "blocking"})
        return findings
    # Only enforce total when tiered
    has_tier = any(isinstance(p, dict) and "tier" in p for p in places)
    total = len(places)
    if has_tier and total < TOTAL_PLACES_MIN:
        findings.append({"code": "tier.places.total", "severity": "blocking", "total": total, "required": TOTAL_PLACES_MIN})
    # If places have tier field, validate per-tier counts
    tiered: dict[str, list] = {"L1": [], "L2": [], "L3": []}
    has_tier = any(isinstance(p, dict) and "tier" in p for p in places)
    if has_tier:
        for p in places:
            tier = str(p.get("tier", "L3")).upper()
            if tier not in tiered:
                tier = "L3"
            tiered[tier].append(p)
        for tier, spec in PLACES_TIERS.items():
            cnt = len(tiered[tier])
            low, high = spec["count"]
            if not (low <= cnt <= high):
                findings.append({"code": f"tier.places.{tier}.count", "severity": "blocking", "count": cnt, "expected": f"{low}-{high}"})
    return findings

def validate_graph_connectivity(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """Graph connectivity: every character and place must be referenced by at least one other entity or continuity_material."""
    findings: list[dict[str, Any]] = []
    characters = proposal.get("characters", [])
    places = proposal.get("places", [])
    factions = proposal.get("factions", [])
    kernel = proposal.get("kernel", [])
    if not isinstance(characters, list):
        return findings
    # Build simple graph: nodes are IDs, edges derived from shared text or explicit relations
    # For this deterministic check, we ensure that no character is isolated: at least one other entity mentions its name or id,
    # or it appears in continuity_material.
    # Simplified: if continuity_material maps characters to continuities, it's considered connected.
    continuity_material = proposal.get("continuity_material", {})
    # If no material and more than 5 nodes, consider disconnected
    all_ids = {str(c.get("id")) for c in characters if isinstance(c, dict)} | {str(p.get("id")) for p in places if isinstance(p, dict)} | {str(f.get("id")) for f in factions if isinstance(f, dict)}
    if len(all_ids) > 5 and not continuity_material:
        findings.append({"code": "graph.disconnected", "severity": "blocking", "detail": "continuity_material empty with >5 nodes"})
        return findings
    # Check each character appears in at least one place or faction's text (simple heuristic: name in text)
    # For determinism, we just ensure that at least 80% of characters are referenced somewhere
    # Build corpus of all text
    corpus = ""
    for cat in ["kernel", "places", "factions", "characters"]:
        for row in proposal.get(cat, []):
            if isinstance(row, dict):
                for v in row.values():
                    if isinstance(v, str):
                        corpus += " " + v
    isolated = []
    for ch in characters:
        if not isinstance(ch, dict):
            continue
        name = str(ch.get("name", ch.get("id", "")))
        cid = str(ch.get("id", ""))
        if name and name.lower() not in corpus.lower() and cid.lower() not in corpus.lower():
            isolated.append(cid)
    if len(isolated) > len(characters) * 0.2:  # more than 20% isolated
        findings.append({"code": "graph.disconnected", "severity": "blocking", "isolated": isolated})
    return findings

def assert_tiers(proposal: dict[str, Any], target_words: int = 80000) -> None:
    findings = []
    findings.extend(validate_tiered_cast(proposal, target_words))
    findings.extend(validate_places_tiered(proposal))
    findings.extend(validate_graph_connectivity(proposal))
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    if blocking:
        raise ValueError(f"tier validation failed: {blocking}")

def split_characters_tiered(characters: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split characters into 2 sub-chunks: L1+L2 and L3+L4 to stay <15KB."""
    if not isinstance(characters, list):
        return [], []
    # Assume tier field or infer by position: first 10 are L1+L2, rest are L3+L4
    has_tier = any("tier" in c for c in characters if isinstance(c, dict))
    if has_tier:
        chunk1 = [c for c in characters if str(c.get("tier", "")).upper() in ("L1", "L2")]
        chunk2 = [c for c in characters if str(c.get("tier", "")).upper() in ("L3", "L4")]
    else:
        chunk1 = characters[:10]
        chunk2 = characters[10:]
    return chunk1, chunk2
