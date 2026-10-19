import json, os, unittest
from gemmascript import check, tok, load_cat, sort_one, parse_chat

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = load_cat(os.path.join(HERE, "catalogue.txt"))
MSG = "Bhai ekta resmed auto cpap lagbe, kal shaam 7 baje"
GOOD = {"items": [{"name": "ResMed Auto CPAP", "qty": 1, "days": None, "quote": "ekta resmed auto cpap"}],
        "slot": "kal shaam 7 baje", "cancel": False, "clarify": ""}
RENT = "Need 2 oxygen concentrator on rent for 1 week"
RGOOD = {"items": [{"name": "Oxygen Concentrator Rental", "qty": 2, "days": 7, "quote": "2 oxygen concentrator on rent"}],
         "slot": "", "cancel": False, "clarify": ""}


class T(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(tok("৮টায়"), ["8", "টায়"])
        self.assertIn("দুটো", tok("দুটো মাটন বিরিয়ানি"))

    def test_good_passes(self):
        self.assertEqual(check(MSG, CAT, GOOD), [])

    def test_english_number_words(self):
        m = "send one resmed auto cpap"
        out = dict(GOOD, items=[dict(GOOD["items"][0], quote="one resmed auto cpap")], slot="")
        self.assertEqual(check(m, CAT, out), [])

    def test_wrong_quantity(self):
        r = check(MSG, CAT, dict(GOOD, items=[dict(GOOD["items"][0], qty=2)]))
        self.assertTrue(any("not in the quote" in x for x in r))

    def test_invented_item(self):
        r = check(MSG, CAT, dict(GOOD, items=[{"name": "Wheelchair", "qty": 1, "quote": "ekta"}]))
        self.assertTrue(any("not in the price list" in x for x in r))

    def test_quote_not_in_message(self):
        r = check(MSG, CAT, dict(GOOD, items=[dict(GOOD["items"][0], quote="5 resmed auto cpap")]))
        self.assertTrue(any("not copied" in x for x in r))

    def test_wrong_item_for_quote(self):
        out = {"items": [{"name": "ResMed Auto CPAP", "qty": 2, "quote": "2 oxygen mask"}], "slot": "", "cancel": False}
        self.assertTrue(any("does not name" in x for x in check("2 oxygen mask", CAT, out)))

    def test_slot_words(self):
        self.assertTrue(check(MSG, CAT, dict(GOOD, slot="aaj raat"))[0].startswith("slot"))

    def test_cancel_both_ways(self):
        self.assertTrue(check("order cancel kore dao", CAT, {"items": [], "cancel": False}))
        self.assertTrue(check(MSG, CAT, dict(GOOD, cancel=True)))
        self.assertEqual(check("order cancel kore dao", CAT, {"items": [], "cancel": True}), [])

    def test_rental_passes_and_prices(self):
        self.assertEqual(check(RENT, CAT, RGOOD), [])
        r = sort_one(lambda p: RGOOD, "v3", RENT, CAT)
        self.assertEqual((r["status"], r["total"]), ("checked", 2 * 7 * 2500))

    def test_rental_days_must_come_from_message(self):
        bad = dict(RGOOD, items=[dict(RGOOD["items"][0], days=10)])
        self.assertTrue(any("not in the message" in x for x in check(RENT, CAT, bad)))

    def test_month_means_thirty_days(self):
        m = "ek cpap machine rent pe chahiye 1 month"
        out = {"items": [{"name": "CPAP Machine Rental", "qty": 1, "days": 30, "quote": "ek cpap machine rent pe"}], "slot": "", "cancel": False}
        self.assertEqual(check(m, CAT, out), [])

    def test_rental_item_needs_rental_word(self):
        out = {"items": [{"name": "CPAP Machine Rental", "qty": 1, "days": 5, "quote": "1 cpap machine"}], "slot": "", "cancel": False}
        self.assertTrue(any("no rental word" in x for x in check("1 cpap machine 5 din", CAT, out)))

    def test_purchase_item_cannot_carry_days(self):
        bad = dict(GOOD, items=[dict(GOOD["items"][0], days=3)])
        self.assertTrue(any("days only belong" in x for x in check(MSG, CAT, bad)))

    def test_rent_message_with_purchase_item_is_flagged(self):
        m = "1 resmed auto cpap rent pe"
        out = {"items": [{"name": "ResMed Auto CPAP", "qty": 1, "quote": "1 resmed auto cpap"}], "slot": "", "cancel": False}
        self.assertTrue(any("mentions renting" in x for x in check(m, CAT, out)))
        self.assertEqual(check(m, CAT, dict(out, clarify="rent or buy?")), [])

    def test_clarify_accepts_empty_items(self):
        out = {"items": [], "slot": "", "cancel": False, "clarify": "wheelchair is not in the price list"}
        self.assertEqual(check("2 wheelchair lagbe", CAT, out), [])
        self.assertTrue(check("2 wheelchair lagbe", CAT, dict(out, clarify="")))

    def test_dropped_item_is_caught(self):
        m = "3 nasal cannula 1 connector tube lagbe kal sokale"
        out = {"items": [{"name": "Oxygen Nasal Cannula", "qty": 3, "quote": "3 nasal cannula"}], "slot": "", "cancel": False}
        self.assertTrue(any("leaves it out" in x and "Connector Tube" in x for x in check(m, CAT, out)))
        both = dict(out, items=out["items"] + [{"name": "Connector Tube", "qty": 1, "quote": "1 connector tube"}])
        self.assertEqual(check(m, CAT, both), [])
        self.assertEqual(check(m, CAT, dict(out, clarify="second item unclear")), [])

    def test_dropped_item_ignored_when_cancelling(self):
        m = "cancel 2 oxygen mask"
        self.assertEqual(check(m, CAT, {"items": [], "cancel": True}), [])

    def test_retry_then_print(self):
        calls = []
        def ask(p):
            calls.append(p)
            return dict(GOOD, items=[dict(GOOD["items"][0], qty=2)]) if len(calls) == 1 else GOOD
        r = sort_one(ask, "v3", MSG, CAT)
        self.assertEqual((r["status"], len(calls), r["total"]), ("retried", 2, 27000))
        self.assertIn("rejected", calls[1])

    def test_fallback_prints_no_numbers(self):
        r = sort_one(lambda p: None, "v3", MSG, CAT)
        self.assertTrue(r["status"].startswith("not verified"))
        self.assertEqual((r["items"], r["total"]), ([], None))

    def test_model_cannot_set_price(self):
        out = dict(GOOD, items=[dict(GOOD["items"][0], price=1)])
        self.assertEqual(sort_one(lambda p: out, "v3", MSG, CAT)["total"], 27000)

    def test_gold_file(self):
        names = {c["name"] for c in CAT}
        with open(os.path.join(HERE, "gold.json"), encoding="utf-8") as fh:
            for g in json.load(fh):
                for x in g["items"]:
                    self.assertIn(x[0], names)
                    self.assertTrue(x[1] >= 1)

    def test_parse_chat(self):
        m = parse_chat("[19/10/26, 9:12 AM] Riya Sen: 2 raita\nlagbe\n[19/10/26, 9:14 AM] Amit: hi")
        self.assertEqual((len(m), m[0]["text"]), (2, "2 raita lagbe"))


if __name__ == "__main__":
    unittest.main()
