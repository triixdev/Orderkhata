# Orderkhata

Sorts WhatsApp orders for a small medical equipment shop in Kolkata (oxygen concentrators, CPAP machines and accessories). Customers write in Bengali, Hindi, English or a mix. A local Gemma model reads each message, and plain code checks every answer before anything is printed.

Built for the Hacktoberfest Open-Source AI Challenge, Week 2 (Side Hustle). Entering: Best Use of Gemma.

## How it works

1. Gemma (through Ollama, on your own computer) reads one customer message and returns items, quantities, rental days, the delivery time words and a short quote of the customer's own words.
2. `check()` in `gemmascript.py` audits that answer against the message and the price list. Every quantity must appear in the quote. Rental days must come from the message. Item names must be in the price list.
3. A failed answer gets one retry with the exact problems listed. If it fails again, the message is handed back untouched for a person to read.
4. Prices and totals are never taken from the model. They are computed from `catalogue.txt`.

## Files

- `gemmascript.py`: the model call, the checker and the evaluation. Standard library only.
- `tests.py`: 23 unit tests for the checker and the pipeline (`python tests.py`).
- `gold.json`: 25 test messages with the correct answers. They were written with AI help to imitate customer messages. They are not real customers.
- `catalogue.txt`: the price list.
- eval_v1.jsonl and eval_v2.jsonl: raw output of run 1. eval_v3.jsonl: raw output of run 2 (v3 only). eval_v3_run1.jsonl: v3 from run 1. : raw output of the evaluation, one line per message.
- `index.html`: a single-file demo page. It uses fixed rules, not a model, because a browser page cannot run a model under its privacy settings. It makes no network requests and stores nothing.

## Run it

```
ollama pull gemma3:4b
python tests.py
python gemmascript.py eval --model gemma3:4b --versions v1 v2 v3
python gemmascript.py sort chat.txt --model gemma3:4b
```

`chat.txt` is a WhatsApp export. Do not commit real chats to this repository.

## Credits and sources

- Gemma, an open-weight model from Google, run locally through Ollama.
- Prices in catalogue.txt come from the shop's public IndiaMART listing and were confirmed by the shop owner.
