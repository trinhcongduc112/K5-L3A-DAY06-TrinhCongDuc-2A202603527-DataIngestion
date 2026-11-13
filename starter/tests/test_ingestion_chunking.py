"""Run from starter/:  python -m unittest discover -s tests -t . -v"""
import unittest

from src.chunking import SectionIndex, by_paragraph, fixed_size, make_chunks, parse_blocks
from src.config import STRATEGIES
from src.ingestion import MIN_UNIT_CHARS, MIN_UNITS, load_markdown_corpus, normalize_text
from src.models import DocumentPage


def page(text: str, **meta) -> DocumentPage:
    return DocumentPage("doc", "http://x", 1, text, {"title": "T", "section": "s", "subsection": "u", **meta})


class NormalizeTests(unittest.TestCase):
    def test_changes_and_idempotence(self):
        raw = "Intro text  \n\n\n\n## Part {#part}\n<a id=\"x\" />\nbody\n```yaml\n# keep  \na:   1\n```\n## \n* link\n"
        out = normalize_text(raw)
        self.assertNotIn(" ", out)
        self.assertNotIn("{#part}", out)
        self.assertNotIn("<a id", out)
        self.assertIn("## Part\n", out)
        self.assertIn("a:   1", out)                         # code content untouched
        self.assertIn("## What's next", out)                 # empty heading restored (a heading was already seen)
        self.assertNotIn("\n\n\n", out)
        self.assertEqual(normalize_text(out), out)

    def test_first_empty_heading_is_prerequisites(self):
        self.assertTrue(normalize_text("## \nText").startswith("## Before you begin"))


class ParseTests(unittest.TestCase):
    def test_fenced_comments_are_not_headings_and_fences_are_atomic(self):
        text = "Intro\n\n## Real\n\ntext\n\n   ```bash\n   ## not a heading\n\n   # comment\n   ```\n\nafter"
        blocks = parse_blocks(text)
        self.assertEqual([b.title for b in blocks if b.kind == "heading"], ["Real"])
        code = [b for b in blocks if b.kind == "code"]
        self.assertEqual(len(code), 1)
        self.assertIn("# comment", text[code[0].start:code[0].end])

    def test_section_index(self):
        text = "Intro\n\n## A\n\nx\n\n### A1\n\ny\n\n## B\n\nz"
        idx = SectionIndex(text)
        self.assertEqual(idx.lookup(0), ((), 1))
        self.assertEqual(idx.lookup(text.index("x")), (("A",), 2))
        self.assertEqual(idx.lookup(text.index("y")), (("A", "A1"), 2))
        self.assertEqual(idx.lookup(text.index("z")), (("B",), 3))


class SyntheticChunkingTests(unittest.TestCase):
    def test_fixed_size_arguments(self):
        with self.assertRaises(ValueError):
            fixed_size(page("a b c"), size=10, overlap=10)

    def test_oversized_paragraph_is_split_but_small_ones_are_not(self):
        big = " ".join(f"Sentence number {i} is here." for i in range(80))
        text = f"## Head\n\nShort para.\n\n{big}\n\n## Next\n\nTail."
        chunks = by_paragraph(page(text), max_size=500, min_size=100)
        for c in chunks:
            self.assertEqual(c.text, text[c.metadata["char_start"]:c.metadata["char_end"]])
            self.assertLessEqual(len(c.text), 500 + 10)
        self.assertTrue(any(c.text.startswith("## Next") for c in chunks))     # H2 always starts a chunk
        self.assertFalse(any(c.text.strip().startswith("## Head") and c.text.strip() == "## Head" for c in chunks))


class CorpusInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages, cls.log = load_markdown_corpus()

    def test_corpus_meets_lab_minimums(self):
        self.assertGreaterEqual(len(self.pages), MIN_UNITS)
        self.assertTrue(all(len(p.text) >= MIN_UNIT_CHARS for p in self.pages))
        self.assertEqual(len({p.document_id for p in self.pages}), len(self.pages))
        self.assertTrue(all(r["status"] == "ok" for r in self.log))

    def test_all_strategies_keep_invariants(self):
        for name, cfg in STRATEGIES.items():
            ids = set()
            for p in self.pages:
                covered = bytearray(len(p.text))
                for c in make_chunks(p, cfg):
                    s, e = c.metadata["char_start"], c.metadata["char_end"]
                    with self.subTest(strategy=name, chunk=c.chunk_id):
                        self.assertEqual(p.text[s:e], c.text)                     # verbatim slice
                        self.assertTrue(c.text.strip())
                        self.assertNotIn(c.chunk_id, ids)
                        self.assertGreaterEqual(c.page, 1)
                        self.assertGreaterEqual(c.metadata["page_end"], c.page)
                    ids.add(c.chunk_id)
                    covered[s:e] = b"\x01" * (e - s)
                missing = [i for i, ch in enumerate(p.text) if not ch.isspace() and not covered[i]]
                self.assertEqual(missing, [], f"{name}: uncovered chars in {p.document_id}")

    def test_fixed_size_respects_cap_and_words(self):
        for name in ("A", "A2"):
            cfg = STRATEGIES[name]
            for p in self.pages:
                for c in fixed_size(p, cfg["size"], cfg["overlap"]):
                    s, e = c.metadata["char_start"], c.metadata["char_end"]
                    self.assertLessEqual(len(c.text), cfg["size"])
                    if not (s == 0 or p.text[s - 1].isspace()):
                        # same exception: inside an unbreakable token the next window simply continues where the last ended
                        self.assertFalse(any(ch.isspace() for ch in p.text[max(0, s - cfg["overlap"]):s]),
                                         f"{name} starts mid-word in {p.document_id}@{s}")
                    if not (e == len(p.text) or p.text[e].isspace()):
                        # unavoidable only for a token with no whitespace in the whole second half of the window
                        # (e.g. the 2000 digits of pi printed by the Job example)
                        self.assertFalse(any(ch.isspace() for ch in p.text[s + cfg["size"] // 2:e]),
                                         f"{name} ends mid-word in {p.document_id}@{e}")

    def test_by_paragraph_structure(self):
        cfg = STRATEGIES["B"]
        over = 0
        for p in self.pages:
            for c in by_paragraph(p, cfg["max_size"], cfg["min_size"]):
                self.assertEqual(c.page, c.metadata["page_end"], "B must never cross an H2 boundary")
                self.assertFalse(all(line.startswith("#") for line in c.text.splitlines() if line.strip()),
                                 "a heading must not stand alone")
                if len(c.text) > cfg["max_size"]:
                    over += 1
                    self.assertLessEqual(len(c.text), cfg["max_size"] + 120)       # only a heading line may overflow
        self.assertLessEqual(over, 10)


if __name__ == "__main__":
    unittest.main()
