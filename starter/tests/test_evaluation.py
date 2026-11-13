import unittest

from src.evaluation import evaluate_query, summarize

Q = {"id": "q", "gold_source_id": "docA", "evidence_quote": "alpha  beta\ngamma", "evidence_start": 100,
     "evidence_end": 120, "alt_evidence": [{"source_id": "docB", "evidence_quote": "alpha beta gamma",
                                            "evidence_start": 10, "evidence_end": 26}],
     "filter": {"section": "s1"}}


def hit(rank, doc, text, start=0, end=50, section="s1"):
    return {"rank": rank, "chunk_id": f"{doc}{rank}", "document_id": doc, "text": text,
            "metadata": {"char_start": start, "char_end": end, "section": section}}


class EvaluationTests(unittest.TestCase):
    def test_hit_is_whitespace_insensitive_and_needs_the_right_document(self):
        ev = evaluate_query(Q, [hit(1, "docX", "alpha beta gamma"), hit(2, "docA", "so alpha\n beta   gamma yes", 90, 140)])
        self.assertFalse(ev["hit_at_1"])
        self.assertTrue(ev["hit_at_3"])
        self.assertEqual(ev["first_hit_rank"], 2)

    def test_alternative_source_is_accepted(self):
        ev = evaluate_query(Q, [hit(1, "docB", "xx alpha beta gamma xx", 0, 40)])
        self.assertTrue(ev["hit_at_1"])

    def test_partial_evidence_is_classified_as_split(self):
        ev = evaluate_query(Q, [hit(1, "docA", "only alpha beta", 90, 110)])
        self.assertFalse(ev["hit_at_3"])
        self.assertEqual(ev["failure_mode"], "evidence_split")

    def test_failure_modes_and_scope(self):
        ev = evaluate_query(Q, [hit(1, "docX", "nothing", section="s2"), hit(2, "docA", "other part", 500, 600)])
        self.assertEqual(ev["failure_mode"], "right_document_other_passage")
        self.assertFalse(ev["scope_compliant_top3"])
        ev2 = evaluate_query({**Q, "filter": None}, [hit(1, "docX", "nothing")])
        self.assertEqual(ev2["failure_mode"], "wrong_document")
        self.assertIsNone(ev2["scope_compliant_top3"])

    def test_summarize_counts(self):
        def tr(strategy, qid, h1, h3, flt, ok):
            return {"strategy": strategy, "split": "dev", "type": "direct", "question_id": qid, "hit_at_1": h1,
                    "hit_at_3": h3, "first_hit_rank": 1 if h1 else (2 if h3 else None), "failure_mode": None,
                    "filter": flt, "filter_applied": bool(flt), "scope_compliant_top3": ok if flt else None}
        s = summarize([tr("B", "a", True, True, None, None), tr("B", "b", False, True, {"section": "x"}, True),
                       tr("B", "c", False, False, {"section": "x"}, False)])
        m = s["B"]["dev"]
        self.assertEqual((m["hit_at_1"], m["hit_at_3"], m["scope_compliant_top3"]), ("1/3", "2/3", "1/2"))
        self.assertEqual(m["mrr_at_3"], round((1 + 0.5 + 0) / 3, 3))


if __name__ == "__main__":
    unittest.main()
