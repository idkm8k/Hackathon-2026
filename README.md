# Hanzi Coach

Hanzi Coach is a handwriting practice prototype. It uses Hanzi Writer's character stroke data to check a learner's drawing, record attempts, and give stroke-order or direction feedback when the drawn path matches a known stroke clearly.

## Run locally on Windows

From this folder, open PowerShell and run:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py loaddata enclosures.json
python manage.py runserver
```

Open `http://localhost:8000` in a browser. Attempt history is stored in the local SQLite database. The database and virtual environment are intentionally excluded from Git.

Gemini tips and ElevenLabs speech are optional. If you use them, set `GEMINI_API_KEY` or `ELEVENLABS_API_KEY` in your local PowerShell session. Keep keys out of source files and Git.

## Phone demo

With Django running, start a Cloudflare quick tunnel pointed at `http://localhost:8000`. Keep both processes running while the phone uses the tunnel link. Phone attempts are saved to the laptop's local database.

## Project layout

- `coach/` — practice endpoints, diagnosis history, and page templates
- `hanzi/` — Django project settings and URL routing
- `manage.py` — Django command entry point
