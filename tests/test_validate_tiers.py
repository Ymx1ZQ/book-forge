import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "validate.py"
BF_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"

def load_validate():
    spec = importlib.util.spec_from_file_location("validate_mod", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def load_bf():
    spec = importlib.util.spec_from_file_location("bf_validate", BF_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

val = load_validate()
bf = load_bf()

def make_char(tier, idx, words):
    base = "word " * words
    base = base.strip()
    if tier == "L1":
        return {"id": f"CHR-{idx:04d}", "name": f"Name{idx}", "tier": tier, "summary": base, "want": "want", "need": "need", "flaw": "flaw", "wound": "wound", "arc": "arc", "voice": "voice", "secret": "secret"}
    else:
        return {"id": f"CHR-{idx:04d}", "name": f"Name{idx}", "tier": tier, "summary": base}

def valid_proposal():
    # L1 2, L2 5, L3 6, L4 10 = 23 chars; places 4+5+6=15
    chars = [make_char("L1", i, 300) for i in range(2)] + [make_char("L2", i+2, 175) for i in range(5)] + [make_char("L3", i+7, 75) for i in range(6)] + [make_char("L4", i+13, 10) for i in range(10)]
    places = [{"id": f"PLC-{i:04d}", "name": f"Place{i}", "tier": "L1" if i<4 else "L2" if i<9 else "L3", "summary": "place"} for i in range(15)]
    return {
        "kernel": [{"id": "LAW-0001", "summary": "law"}],
        "eras": [{"id": "ERA-0001", "name": "Era", "order": 1, "when": "2087", "material": ["archive skiffs on the canals", "no radio below the waterline", "credit is a favour owed"]}],
        "events": [{"id": "EVT-0001", "era": "ERA-0001", "order": 1, "summary": "event"}],
        "places": places,
        "factions": [{"id": "FAC-0001", "summary": "faction"}],
        "characters": chars,
        "themes": ["t"],
        "style": {"tense": "past", "person": "third-limited"},
        "continuity_material": {"CNT-0001": ["CHR-0000"]},
        "book_local": {},
        "unresolved_questions": []
    }

class ValidateTiersTests(unittest.TestCase):
    def test_tier_counts_and_word_ranges(self):
        prop = valid_proposal()
        self.assertEqual(val.validate_tiered_cast(prop), [])
        self.assertEqual(val.validate_places_tiered(prop), [])
        # No blocking
        val.assert_tiers(prop)

    def test_L1_requires_fields(self):
        prop = valid_proposal()
        # Remove a required field from L1
        prop["characters"][0].pop("want")
        findings = val.validate_tiered_cast(prop)
        self.assertTrue(any(f["code"] == "tier.L1.field.want" for f in findings))

    def test_L1_word_range(self):
        prop = valid_proposal()
        prop["characters"][0]["summary"] = "short"  # ~1 word, fail 250-350
        findings = val.validate_tiered_cast(prop)
        self.assertTrue(any("tier.L1.words" in f["code"] for f in findings))

    def test_total_named_threshold(self):
        prop = valid_proposal()
        # Reduce to 10 chars -> should fail total_named 22
        prop["characters"] = prop["characters"][:10]
        findings = val.validate_tiered_cast(prop)
        self.assertTrue(any(f["code"] == "tier.total_named" for f in findings))

    def test_places_total(self):
        prop = valid_proposal()
        prop["places"] = prop["places"][:5]
        findings = val.validate_places_tiered(prop)
        self.assertTrue(any(f["code"] == "tier.places.total" for f in findings))

    def test_graph_connectivity(self):
        prop = valid_proposal()
        prop["continuity_material"] = {}
        # Make isolated: remove names from corpus effect? Our graph checks continuity_material empty with >5 nodes => disconnected
        findings = val.validate_graph_connectivity(prop)
        self.assertTrue(any(f["code"] == "graph.disconnected" for f in findings))

    def test_scaled_total(self):
        # For 40k, required is 11
        prop = valid_proposal()
        prop["characters"] = prop["characters"][:12]
        # 40k should pass with 12 (>=11)
        self.assertEqual(val.validate_tiered_cast(prop, target_words=40000), [])
        # 80k should fail with 12 (<22)
        findings = val.validate_tiered_cast(prop, target_words=80000)
        self.assertTrue(any(f["code"] == "tier.total_named" for f in findings))

    def test_split_characters_into_two_chunks(self):
        prop = valid_proposal()
        c1, c2 = val.split_characters_tiered(prop["characters"])
        self.assertEqual(len(c1) + len(c2), len(prop["characters"]))
        self.assertTrue(len(c1) > 0 and len(c2) > 0)
        # Check within per-chunk budget via book_forge helper
        self.assertLessEqual(bf.chunk_bytes({"characters": c1}), bf.DESIGN_CHUNK_MAX_BYTES)
        self.assertLessEqual(bf.chunk_bytes({"characters": c2}), bf.DESIGN_CHUNK_MAX_BYTES)
        # Also test book_forge split_proposal
        chunks = bf.split_proposal_into_chunks(prop)
        char_chunks = [c for c in chunks if "characters" in c]
        self.assertEqual(len(char_chunks), 2)
        for ch in char_chunks:
            self.assertLessEqual(bf.chunk_bytes({"characters": ch["characters"]}), bf.DESIGN_CHUNK_MAX_BYTES)

    def test_book_forge_integration_tier_validation(self):
        # Ensure book_forge validate_universe_design calls tier validation for tiered proposal
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        bf.init_project(tmp, "T")
        # Create a tiered proposal that fails
        bad = valid_proposal()
        bad["characters"] = bad["characters"][:5]  # too few
        findings = bf.validate_universe_design(tmp, bad)
        self.assertTrue(any("tier" in f["code"] for f in findings))

if __name__ == "__main__":
    unittest.main()
