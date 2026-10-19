#!/usr/bin/env python3
"""Gemma proposes, code checks, code supplies the prices. Built for a medical equipment shop. Standard library only.

  python gemmascript.py eval --model gemma3:4b --versions v1 v2 v3
  python gemmascript.py sort chat.txt --model gemma3:4b

The model reads one customer message and returns items, quantities and the words it
relied on. check() audits that answer against the message and the price list. A failing
answer gets one retry, then the message is quoted back for a person. Prices and totals
are never taken from the model. Everything runs against a local Ollama server.
"""
import argparse, json, os, re, sys, unicodedata, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIG = {c: str(i) for i, c in enumerate("০১২৩৪৫৬৭৮৯")}
DIG.update({c: str(i) for i, c in enumerate("०१२३४५६७८९")})
NW = {}
for _p in ("ek:1 এক:1 एक:1 একটা:1 একটি:1 dui:2 duto:2 do:2 দুই:2 দুটো:2 দুটি:2 দুইটা:2 दो:2 tin:3 তিন:3 তিনটে:3 "
           "তিনটা:3 तीन:3 char:4 চার:4 চারটে:4 চারটা:4 चार:4 panch:5 paanch:5 পাঁচ:5 পাঁচটা:5 पांच:5 पाँच:5 chhoy:6 "
           "ছয়:6 छह:6 sat:7 সাত:7 सात:7 aat:8 আট:8 आठ:8 noy:9 नौ:9 dosh:10 দশ:10 दस:10 ekta:1 ekti:1 one:1 two:2 three:3 four:4 five:5 six:6 seven:7 eight:8 nine:9 ten:10").split():
    _k, _v = _p.split(":")
    NW[unicodedata.normalize("NFC", _k)] = int(_v)
CAN = {unicodedata.normalize("NFC", w) for w in "cancel বাতিল रद्द".split()}
WORDS = lambda t: {unicodedata.normalize("NFC", w) for w in t.split()}
RENT = WORDS("rent rental hire bhara kiraya ভাড়া ভাড়ায় ভাড়াও किराया किराये")
BUY = WORDS("buy purchase kinbo kinte kharid কিনব কিনতে খরিদ खरीद")
MONTH = WORDS("month months mahina মাস महीना महीने")
WEEK = WORDS("week weeks hapta সপ্তাহ हफ्ता")
STRIP = {"rental", "rent", "hire", "on", "pe"}
ORD = {unicodedata.normalize("NFC", w) for w in "lagbe lagbo chai chahiye order dorkar want need please dena dao লাগবে চাই দরকার चाहिए चाहिये".split()}


def tok(t):
    t = unicodedata.normalize("NFC", t).lower()
    t = "".join(DIG.get(c, c) for c in t)
    out, cur, kind = [], "", None
    for c in t:
        k = "d" if c.isdigit() and c.isascii() else "w" if unicodedata.category(c)[0] in "LM" else None
        if k and k == kind:
            cur += c
            continue
        if cur:
            out.append(cur)
        cur, kind = (c, k) if k else ("", None)
    if cur:
        out.append(cur)
    return out


def nz(s):
    for a, b in (("ee", "i"), ("oo", "u"), ("ph", "f"), ("sh", "s"), ("h", ""), ("o", "a"), ("w", "v")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def lev(a, b):
    p = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        c = [i]
        for j in range(1, len(b) + 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (a[i - 1] != b[j - 1])))
        p = c
    return p[-1]


def load_cat(path):
    cat = []
    for line in open(path, encoding="utf-8"):
        p = [x.strip() for x in line.split("|")]
        if line.startswith("#") or len(p) < 2 or not p[0]:
            continue
        try:
            price = float(p[1])
        except ValueError:
            continue
        names = [p[0]] + [a.strip() for a in (p[3] if len(p) > 3 else "").split(",") if a.strip()]
        unit = p[2] if len(p) > 2 else "piece"
        keep = (lambda w: w not in STRIP) if unit == "day" else (lambda w: True)
        keys = [[nz(w) for w in tok(n) if keep(w)] for n in names]
        cat.append({"name": p[0], "price": price, "unit": unit, "aliases": names[1:], "keys": [k for k in keys if k]})
    return cat


def contains(seq, sub):
    return any(seq[i:i + len(sub)] == sub for i in range(len(seq) - len(sub) + 1))


def mentioned(mt, cat):
    """Price list items that the message names, longest match first, no word used twice.
    Same matching idea as the demo page: spelling swaps ignored, one letter miss allowed on long names."""
    rent = any(w in RENT for w in mt)
    n = [nz(w) for w in mt]
    cands = []
    for c in cat:
        for k in c["keys"]:
            kj = "".join(k)
            for i in range(len(n) - len(k) + 1):
                d = lev("".join(n[i:i + len(k)]), kj)
                if d == 0 or (d == 1 and len(kj) >= 6):
                    cands.append((-len(k), d, (c["unit"] == "day") != rent, i, c["name"]))
    cands.sort()
    taken, found = set(), []
    for negl, _d, _p, i, name in cands:
        span = range(i, i - negl)
        if any(j in taken for j in span):
            continue
        taken.update(span)
        found.append(name)
    return found


def check(text, cat, out):
    """Returns a list of failures. An empty list means the answer passes."""
    if not isinstance(out, dict) or not isinstance(out.get("items"), list):
        return ["answer was not a JSON object with an items list"]
    f, mt, seen = [], tok(text), set()
    by = {c["name"].lower(): c for c in cat}
    for it in out["items"]:
        if not isinstance(it, dict):
            f.append("an item was not an object")
            continue
        name = str(it.get("name", "")).strip()
        c = by.get(name.lower())
        if not c:
            f.append("not in the price list: " + name)
            continue
        if name.lower() in seen:
            f.append("item listed twice: " + name)
        seen.add(name.lower())
        q = it.get("qty")
        if not isinstance(q, int) or isinstance(q, bool) or not 1 <= q <= 200:
            f.append("quantity for %s must be a whole number from 1 to 200" % name)
            continue
        if c["unit"] == "day":
            d = it.get("days")
            nums = {int(w) for w in mt if w.isdigit()} | {NW[w] for w in mt if w in NW}
            ok = set(nums) | ({n * 30 for n in nums} if any(w in MONTH for w in mt) else set()) | ({n * 7 for n in nums} if any(w in WEEK for w in mt) else set())
            if not any(w in RENT for w in mt):
                f.append("%s is a rental but the message has no rental word" % name)
            if not isinstance(d, int) or isinstance(d, bool) or not 1 <= d <= 365:
                f.append("days for %s must be a whole number from 1 to 365" % name)
            elif d not in ok:
                f.append("%d days is not in the message for %s" % (d, name))
        elif it.get("days") not in (None, 0):
            f.append("days only belong on rental items: " + name)
        qt = tok(str(it.get("quote", "")))
        if not qt or not contains(mt, qt):
            f.append("quote for %s is not copied from the message" % name)
            continue
        if not any((w.isdigit() and int(w) == q) or NW.get(w) == q for w in qt):
            f.append("quantity %d is not in the quote for %s" % (q, name))
        if not any(all(any(lev(nz(w), k) <= (1 if len(k) >= 6 else 0) for w in qt) for k in key) for key in c["keys"]):
            f.append("quote does not name " + name)
    slot = str(out.get("slot") or "")
    if slot.strip() and not set(tok(slot)) <= set(mt):
        f.append("slot words are not in the message")
    can = any(w in CAN for w in mt)
    if out.get("cancel") is True and not can:
        f.append("cancel is true but the message has no cancellation word")
    if can and out.get("cancel") is not True:
        f.append("the message has a cancellation word but cancel is not true")
    cl = out.get("clarify")
    if cl not in (None, "") and not isinstance(cl, str):
        f.append("clarify must be text or empty")
    if not can and not cl:
        named = {str(i.get("name", "")).strip().lower() for i in out["items"] if isinstance(i, dict)}
        for name in dict.fromkeys(mentioned(mt, cat)):
            if name.lower() not in named:
                f.append("the message names %s but the answer leaves it out" % name)
    if out["items"] and all(by.get(str(i.get("name", "")).strip().lower(), {}).get("unit") != "day" for i in out["items"] if isinstance(i, dict)) \
            and any(w in RENT for w in mt) and not any(w in BUY for w in mt) and not cl:
        f.append("the message mentions renting but no rental item was returned and clarify is empty")
    if not out["items"] and out.get("cancel") is not True and not cl and any(w in ORD for w in mt):
        f.append("message looks like an order but no items were returned")
    return f


SHAPE = ('Reply with JSON only: {"items": [{"name": exact name from the price list, "qty": whole number, '
         '"days": whole number of rental days for rental items or null, '
         '"quote": the customer\'s own words that show this item and its quantity}], '
         '"slot": the customer\'s own words about when they want it, or "", "cancel": true or false, '
         '"clarify": "" or one short reason the owner must ask the customer.}')


def prompt(version, text, cat, fails=None):
    names = ", ".join(c["name"] for c in cat)
    full = "\n".join("- %s (also written: %s)" % (c["name"], ", ".join(c["aliases"]) or "no other spellings") for c in cat)
    if version == "v1":
        p = "Message from a customer to a Kolkata medical equipment shop: %s\nPrice list: %s\n%s" % (text, names, SHAPE)
    elif version == "v2":
        p = "Message from a customer to a Kolkata medical equipment shop: %s\nPrice list:\n%s\n%s" % (text, full, SHAPE)
    else:
        p = ("Message from a customer to a Kolkata medical equipment shop, in Bengali, Hindi, English or a mix: %s\nPrice list:\n%s\n%s\n"
             "Rules: only list items from the price list. Quantities come only from numbers or number words in the message "
             "(ek, dui, tin, দুটো, तीन and so on). Copy the quote exactly from the message. If the message is a question, "
             "a thank you or has no order, return an empty items list. Set cancel to true only if the message says cancel. "
             "Never guess a quantity. Items with Rental in the name are only for customers who ask to rent or hire. "
             "Days come only from the message (a month is 30 days and a week is 7). If the product is not in the price list, "
             "no quantity is given, or the customer refers to a previous order, say why in clarify and do not guess." % (text, full, SHAPE))
    if fails:
        p += " Your last answer was rejected: " + "; ".join(fails) + ". Fix exactly these problems."
    return p


def ollama(model):
    def ask(p):
        body = json.dumps({"model": model, "stream": False, "format": "json", "options": {"temperature": 0},
                           "messages": [{"role": "user", "content": p}]}).encode()
        req = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
        try:
            return json.loads(json.load(urllib.request.urlopen(req, timeout=180))["message"]["content"])
        except Exception:
            return None
    return ask


def record(out, cat, status, **kw):
    by = {c["name"].lower(): c for c in cat}
    items = []
    for i in out["items"]:
        c = by[i["name"].strip().lower()]
        days = i.get("days") if c["unit"] == "day" else None
        items.append({"name": c["name"], "qty": i["qty"], "days": days, "amt": i["qty"] * (days or 1) * c["price"]})
    return dict(kw, status=status, items=items, total=sum(i["amt"] for i in items), slot=str(out.get("slot") or ""),
                cancel=out.get("cancel") is True, clarify=str(out.get("clarify") or ""), printed=out)


def sort_one(ask, version, text, cat):
    first = ask(prompt(version, text, cat))
    f1 = check(text, cat, first)
    if not f1:
        return record(first, cat, "checked", first=first, second=None, f1=f1, f2=[])
    second = ask(prompt(version, text, cat, f1))
    f2 = check(text, cat, second)
    if not f2:
        return record(second, cat, "retried", first=first, second=second, f1=f1, f2=[])
    return dict(status="not verified, read it yourself", items=[], total=None, slot="", cancel=False, clarify="",
                printed=None, first=first, second=second, f1=f1, f2=f2)


def norm(out):
    try:
        return (frozenset((str(i["name"]).lower(), i["qty"], i.get("days") or None) for i in out["items"]),
                out.get("cancel") is True, bool(out.get("clarify")))
    except Exception:
        return None


def run_eval(model, versions):
    cat = load_cat(os.path.join(HERE, "catalogue.txt"))
    gold = json.load(open(os.path.join(HERE, "gold.json"), encoding="utf-8"))
    ask = ollama(model)
    print("| Prompt | Messages | Right on first try, unchecked | Passed checks first try | Printed after one retry | Fell back | Printed but wrong | Asked to clarify when not needed |")
    print("|---|---|---|---|---|---|---|---|")
    for v in versions:
        c = dict(raw=0, ok=0, rt=0, fb=0, bad=0, cau=0)
        with open(os.path.join(HERE, "eval_%s.jsonl" % v), "w", encoding="utf-8") as log:
            for g in gold:
                want = (frozenset((x[0].lower(), x[1], x[2] if len(x) > 2 else None) for x in g["items"]), bool(g["cancel"]), bool(g["clarify"]))
                r = sort_one(ask, v, g["text"], cat)
                c["raw"] += norm(r["first"]) == want
                c["ok"] += r["status"] == "checked"
                c["rt"] += r["status"] == "retried"
                c["fb"] += r["printed"] is None
                wrong = r["printed"] is not None and norm(r["printed"]) != want
                c["bad"] += wrong
                c["cau"] += r["printed"] is not None and bool(r["clarify"]) and not g["clarify"]
                log.write(json.dumps(dict(text=g["text"], gold=g["items"], cancel=g["cancel"], status=r["status"],
                                          first=r["first"], second=r["second"], f1=r["f1"], f2=r["f2"], wrong=wrong),
                                     ensure_ascii=False) + "\n")
        print("| %s | %d | %d | %d | %d | %d | %d | %d |" % (v, len(gold), c["raw"], c["ok"], c["rt"], c["fb"], c["bad"], c["cau"]))
    print("\nRead every line of eval_*.jsonl by hand and name the wrong ones in your write-up.")


CHAT = re.compile(r"^\[?(\d{1,2}[\/.]\d{1,2}[\/.]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?)\]?\s*(?:-\s*)?([^:]{1,40}?):\s(.*)$")


def parse_chat(t):
    out = []
    for l in t.splitlines():
        l = l.replace("‎", "").replace("‏", "").strip()
        m = CHAT.match(l) if l else None
        if m:
            out.append({"who": m.group(3).strip(), "text": m.group(4)})
        elif l and out:
            out[-1]["text"] += " " + l
        elif l:
            out.append({"who": "Unknown", "text": l})
    return out[:500]


def run_sort(path, model):
    cat = load_cat(os.path.join(HERE, "catalogue.txt"))
    ask = ollama(model)
    for m in parse_chat(open(path, encoding="utf-8").read()):
        r = sort_one(ask, "v3", m["text"], cat)
        items = "; ".join("%s x %d%s = Rs %g" % (i["name"], i["qty"], " for %d days" % i["days"] if i["days"] else "", i["amt"]) for i in r["items"])
        if r.get("clarify"):
            items += " | ASK THE CUSTOMER: " + r["clarify"]
        print("%s\t%s\t%s\t%s\t%s\t%s" % (m["who"], r["status"], items or ("cancel" if r["cancel"] else ""),
                                          "" if r["total"] is None else "Rs %g" % r["total"], r["slot"], m["text"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["eval", "sort"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--model", default="gemma3:4b")
    ap.add_argument("--versions", nargs="+", default=["v1", "v2", "v3"])
    a = ap.parse_args()
    if a.cmd == "eval":
        run_eval(a.model, a.versions)
    elif not a.file:
        sys.exit("sort needs a chat file")
    else:
        run_sort(a.file, a.model)
