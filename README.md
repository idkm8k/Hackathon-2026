# Inspiration
I'm an aspiring polyglot and Chinese is the fourth language I'm learning. Since Chinese is not an Indo-European language like the previous three I have taken, but part of a completely different language family, it takes a lot of work to learn. Every stroke order app I tried did the same thing: when I got a stroke wrong, it just told me to memorize the correct one. No reason, no pattern.

But stroke order isn't random. It follows rules and conventions, and if you learn the patterns, you can write a character of any difficulty, even one you've never seen. I wanted to make an app that doesn't just force you to memorize, but understand.

# What it does
Hanzi Coach is a stroke-pattern trainer that adapts to your thinking, not just your strokes. It uses a data base of all your strokes, 12 hours of me hardcoding common pattern problems, and the Gemini API to make a personalized response that's adaptive to you. Instead of memorizing characters, you understand patterns, so that you can write any character of any complexity intuitively.

It's also gamified as an optional mode: land a correct stroke and you blast the enemy, make a mistake or run out of time and the enemy strikes back. They may ragebait you a little if you mess up.

# How I built it
Django backend with SQLite
Hanzi Writer for stroke data and real-time stroke checking
Web Audio API for the synthesized blast sounds
A feedback layer that maps common mistakes to the rule the learner was likely using, and explains which rule takes priority
Cloudflare tunnel so the app can be tested on a phone, so drawing can be by finger.

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

## Limitations

- Stroke orders need review by a Chinese reader before relying on them
- Only enclosure rules exist so far; nested enclosures (like 间) aren't handled
- Stroke detection hasn't been tested on much real handwriting
- No accounts: `user` is a typed name, and endpoints are CSRF-exempt (local demo only)

## Credits

Stroke data and character decompositions come from [Hanzi Writer](https://hanziwriter.org/) and [Make Me a Hanzi](https://github.com/skishore/makemeahanzi) (Arphic Public License).
