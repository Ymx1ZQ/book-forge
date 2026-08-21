import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_catalog", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def read(self, relative):
        return json.loads((self.project / relative).read_text())

    def test_arbitrary_book_network_and_registry_membership(self):
        first = self.bf.add_book(self.project, "First")
        second = self.bf.add_book(self.project, "Second")
        self.assertEqual((first["id"], second["id"]), ("BOOK-0001", "BOOK-0002"))
        self.assertEqual(self.read("books/BOOK-0001/book.yaml")["continuity"], "CNT-0001")

        collection = self.bf.collection_add(self.project, "Main Saga", [first["id"], second["id"]])
        self.assertEqual(collection["books"], ["BOOK-0001", "BOOK-0002"])
        self.assertNotIn("collections", self.read("books/BOOK-0001/book.yaml"))

        relation = self.bf.add_relation(
            self.project,
            "sequel_of",
            [second["id"], first["id"]],
            obligations=["Resolve the signal"],
        )
        self.assertEqual(relation["endpoints"], ["BOOK-0002", "BOOK-0001"])
        self.assertRegex(relation["obligations"][0]["id"], r"^OBL-\d{4}$")
        self.assertEqual(len(relation["obligations"][0]["hash"]), 64)

    def test_relation_semantics_and_continuity_boundaries(self):
        a = self.bf.add_book(self.project, "A")["id"]
        b = self.bf.add_book(self.project, "B")["id"]
        alt = self.bf.add_continuity(
            self.project,
            "Alternate",
            fork_from="CNT-0001",
            imports=["UNI-0001#kernel"],
        )["id"]
        c = self.bf.add_book(self.project, "C", continuity=alt)["id"]

        parallel = self.bf.add_relation(self.project, "parallel_to", [b, a])
        self.assertEqual(parallel["endpoints"], [a, b])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.add_relation(self.project, "parallel_to", [a, c])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.add_relation(self.project, "crossover", [a])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.add_relation(self.project, "alternate_of", [a, c])

        cross = self.bf.add_relation(
            self.project,
            "alternate_of",
            [a, c],
            imports=["UNI-0001#kernel"],
        )
        self.assertEqual(cross["imports"][0]["block"], "UNI-0001#kernel")

    def test_rejects_ancestry_cycle_and_preserves_ids(self):
        a = self.bf.add_book(self.project, "A")["id"]
        b = self.bf.add_book(self.project, "B")["id"]
        self.bf.add_relation(self.project, "sequel_of", [b, a])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.add_relation(self.project, "sequel_of", [a, b])

        data = self.read(f"books/{a}/book.yaml")
        data["title"] = "Renamed"
        (self.project / f"books/{a}/book.yaml").write_text(json.dumps(data))
        self.assertEqual(self.bf.list_books(self.project)[0]["id"], a)


if __name__ == "__main__":
    unittest.main()
