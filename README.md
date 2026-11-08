# Hanzi Coach

A handwriting practice app that tells you **which stroke-order rule you broke**, not just that a stroke is wrong. It spots habits across characters and warns you before the next character where they apply.

Built with Django, Hanzi Writer, and the Gemini API. Hackathon prototype.

## Features

- Stroke-by-stroke checking with wrong-order and reversed-stroke feedback
- Names the rule behind order mistakes on enclosure characters: outside before inside (国, 同), close the door last (日, 田), walking radical last (这, 进), fill the cup first (凶)
- Gemini explains the rule using only verified rule text, with a built-in fallback if Gemini is unavailable
- Dashboard showing which rules you break and in which characters
- Heads-up banner before characters where you have a history
- Replay of an attempt: mistakes in red, expected stroke dashed green
- Practice picker that targets your weak rule

## Run (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py loaddata enclosures.json
python manage.py runserver
```

Open `http://localhost:8000`.

Optional: set `GEMINI_API_KEY` in your PowerShell session (never commit it). Without it, the app uses the built-in rule text. `GEMINI_MODEL` and `GEMINI_MAX_PER_MINUTE` (default 30) are also configurable.

## Demo prep

```powershell
python manage.py seed_demo
python manage.py pregen_explanations
python manage.py test
```

- `seed_demo` creates **sample** history for user `demo` (open `/dashboard/?user=demo`). It is sample data, not real usage.
- `pregen_explanations` saves Gemini explanations for the practice characters (about 21 calls, needs a key). Read them before presenting.

For a phone demo, point a Cloudflare quick tunnel at `http://localhost:8000`.

## How it works

Each enclosure character has a pattern with one letter per stroke (`F` frame, `I` contents, `C` closing stroke, `W` frame written last). 日 is `FFIC`. When the browser reports `order_3_4`, `rule_for()` in `coach/enclosure_rules.py` compares the expected and drawn letters to pick the rule, which is saved and used by the explanation, dashboard, heads-up, and practice picker.

## Limitations

- Stroke orders need review by a Chinese reader before relying on them
- Only enclosure rules exist so far; nested enclosures (like 间) aren't handled
- Stroke detection hasn't been tested on much real handwriting
- No accounts: `user` is a typed name, and endpoints are CSRF-exempt (local demo only)

## Credits

Stroke data and character decompositions come from [Hanzi Writer](https://hanziwriter.org/) and [Make Me a Hanzi](https://github.com/skishore/makemeahanzi) (Arphic Public License).
