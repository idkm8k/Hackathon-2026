import json, os, re, urllib.error, urllib.request
from collections import Counter
from django.db.models import Avg, Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Attempt, StrokeMistake

STARTER = list("人大天口日月木水火山你好我他中国学书写永")


def habit_profile(user):
    """Summarize exact stroke-type habits only when seen in multiple characters."""
    groups = {}
    records = StrokeMistake.objects.filter(user=user).exclude(habit="").order_by("-created")
    for mistake in records:
        order = re.fullmatch(r"order_(horizontal|vertical|diagonal)_before_(horizontal|vertical|diagonal)", mistake.habit)
        reverse = re.fullmatch(r"reversed_(horizontal|vertical|diagonal)", mistake.habit)
        if order:
            wrong, expected = order.groups()
            label = "{} before {}".format(wrong.title(), expected)
            detail = "Drew a {} before a {}".format(wrong, expected)
        elif reverse:
            kind = reverse.group(1)
            label = "Reversed {} stroke".format(kind)
            detail = "Reversed a {} stroke".format(kind)
        else:
            continue
        group = groups.setdefault(mistake.habit, {
            "code": mistake.habit, "label": label, "count": 0,
            "char_counts": Counter(), "examples": []})
        group["count"] += 1
        group["char_counts"][mistake.character] += 1
        if len(group["examples"]) < 3:
            group["examples"].append({"character": mistake.character, "detail": detail})
    habits = []
    for group in groups.values():
        counts = group.pop("char_counts")
        group["characters"] = sorted(counts, key=lambda ch: (-counts[ch], ch))
        group["character_count"] = len(counts)
        group["recurring"] = len(counts) >= 2
        habits.append(group)
    habits.sort(key=lambda h: (not h["recurring"], -h["character_count"], -h["count"]))
    return habits


def practice_for(user, n=6):
    """Review characters tied to the user's strongest specific habit first."""
    habits = habit_profile(user)
    focus = habits[0] if habits else None
    targeted = focus["characters"][:3] if focus else []
    stats = (Attempt.objects.filter(user=user).values("character")
             .annotate(avg=Avg("mistakes"), n=Count("id")).order_by("-avg"))
    weak_by_average = [s["character"] for s in stats if s["avg"] and s["avg"] > 0][:4]
    weak = list(dict.fromkeys(targeted + weak_by_average))[:4]
    seen = set(Attempt.objects.filter(user=user).values_list("character", flat=True))
    fresh = [c for c in STARTER if c not in seen]
    out = targeted + [c for c in weak_by_average if c not in targeted]
    out += [c for c in fresh if c not in out]
    out += [c for c in STARTER if c not in out]
    return out[:n], weak, focus


def gemini_result(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "Gemini API key is not available to the Django server."
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":streamGenerateContent?alt=sse")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"thinkingConfig": {"thinkingLevel": "LOW"}},
    }).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    req = urllib.request.Request(url, body, headers)
    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            for raw_line in r:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                data = json.loads(payload)
                for candidate in data.get("candidates", []):
                    content = candidate.get("content", {})
                    for part in content.get("parts", []):
                        if part.get("text") and not part.get("thought"):
                            chunks.append(part["text"])
        answer = "".join(chunks).strip()
        if answer:
            return answer, ""
        return None, "Gemini returned no answer text. Check the Django terminal for details and try again."
    except urllib.error.HTTPError as e:
        try:
            error_data = json.loads(e.read().decode("utf-8"))
            error_info = error_data.get("error", {})
            error_status = error_info.get("status", "")
            error_message = str(error_info.get("message", ""))
            error_message = re.sub(r"(?:AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,})", "[redacted]", error_message)[:240]
            details = error_info.get("details", [])
            reason = next((item.get("reason", "") for item in details
                           if isinstance(item, dict) and item.get("reason")), "")
        except Exception:
            error_status, reason, error_message = "", "", ""
        print("Gemini HTTP error:", e.code, error_status, reason)
        if reason == "API_KEY_INVALID":
            return None, "Google says this Gemini API key is invalid or revoked (API_KEY_INVALID). Create a fresh key in Google AI Studio and set it in the Django server's PowerShell window."
        if error_status == "FAILED_PRECONDITION":
            return None, "Google requires another project setup step for Gemini (FAILED_PRECONDITION). Check the Gemini API project or billing settings."
        if e.code in (401, 403):
            message = "Gemini rejected the API key (HTTP {}). Check that it is valid and available to this project.".format(e.code)
        elif e.code == 404:
            message = "Gemini could not find the configured model (HTTP 404). Check GEMINI_MODEL."
        elif e.code == 429:
            message = "Gemini rate limit or quota reached (HTTP 429). Try again later or check the project quota."
        elif e.code >= 500:
            message = "Google's Gemini service returned HTTP {}. Try again shortly.".format(e.code)
        elif e.code == 400:
            message = "Gemini rejected the request (HTTP 400 {}). {}".format(
                error_status or "INVALID_ARGUMENT",
                error_message or "Check the request or API key settings.")
        else:
            message = "Gemini rejected the request (HTTP {}).".format(e.code)
        return None, message
    except TimeoutError:
        print("Gemini request timed out after 15 seconds.")
        if chunks:
            return "".join(chunks).strip(), ""
        return None, "Gemini took longer than 15 seconds to respond. Check the Django terminal and internet connection, then try again."
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            print("Gemini connection timed out after 15 seconds.")
            if chunks:
                return "".join(chunks).strip(), ""
            return None, "Django could not get a response from Google's Gemini API within 15 seconds. Check the laptop's internet connection and try again."
        print("Gemini connection error:", type(e.reason).__name__)
        return None, "Django could not connect to Google's Gemini API. Check the laptop's internet connection."
    except Exception as e:
        print("Gemini error:", type(e).__name__)
        if chunks:
            return "".join(chunks).strip(), ""
        return None, "Gemini request failed unexpectedly ({}).".format(type(e).__name__)


def gemini(prompt):
    answer, _ = gemini_result(prompt)
    return answer


def index(request):
    return render(request, "coach/index.html")


def api_practice(request):
    user = request.GET.get("user", "guest")
    chars, weak, focus = practice_for(user)
    seen = set(Attempt.objects.filter(user=user).values_list("character", flat=True))
    return JsonResponse({"chars": chars, "weak": weak,
                         "habit": focus["label"] if focus else "",
                         "habit_code": focus["code"] if focus else "",
                         "habit_chars": focus["characters"] if focus else [],
                         "candidate_chars": [c for c in STARTER if c not in seen],
                         "recurring": focus["recurring"] if focus else False})


@csrf_exempt
def api_log(request):
    d = json.loads(request.body)
    user, ch = d.get("user", "guest"), d["character"]
    details = d.get("details", [])
    a = Attempt.objects.create(
        user=user, character=ch,
        mistakes=len(d.get("mistakes", [])),
        completed=d.get("completed", True))
    saved = []
    for m in details:
        points = m.get("points", [])
        diagnosis = m.get("diagnosis", "")
        if not re.fullmatch(r"(?:order_[1-9]\d{0,2}_[1-9]\d{0,2}|reversed_[1-9]\d{0,2})", diagnosis):
            diagnosis = ""
        habit = m.get("habit", "")
        if not re.fullmatch(
            r"(?:order_(?:horizontal|vertical|diagonal)_before_(?:horizontal|vertical|diagonal)|reversed_(?:horizontal|vertical|diagonal))",
            habit,
        ):
            habit = ""
        saved.append(StrokeMistake(
            attempt=a, user=user, character=ch,
            stroke_num=m["stroke"], board_size=m.get("size", 300),
            drawn_points=json.dumps(points), diagnosis=diagnosis, habit=habit))
    StrokeMistake.objects.bulk_create(saved)
    diagnosis = next((m.diagnosis for m in saved if m.diagnosis), "")
    return JsonResponse({"ok": True, "diagnosis": diagnosis})


@csrf_exempt
def api_tip(request):
    d = json.loads(request.body)
    user = d.get("user", "guest")
    ch = d["character"]
    now = d.get("mistakes", [])
    hist = Counter(StrokeMistake.objects.filter(user=user, character=ch)
                   .values_list("stroke_num", flat=True))
    prompt = (
        "You are a friendly Mandarin handwriting coach. "
        "A learner just wrote the character " + ch + ". "
        "This attempt they made mistakes on stroke number(s) "
        + str(now or "none") + ". "
        "Their all-time mistakes per stroke number for this character: "
        + str(dict(hist) or "none yet") + ". "
        "In at most 2 short sentences, state the stroke order rule "
        "they likely broke. "
        "Examples: top to bottom, left to right, "
        "horizontal before vertical, outside before inside. "
        "Then give one memorable mnemonic. "
        "Plain spoken English, no markdown, no emojis."
    )
    tip = gemini(prompt)
    if not tip:
        tip = ("Remember: top to bottom, left to right, "
               "horizontals before verticals. "
               "Slow down and picture the next stroke before you draw it.")
    return JsonResponse({"tip": tip})


@csrf_exempt
def api_ask(request):
    d = json.loads(request.body)
    character = str(d.get("character", ""))[:4]
    question = str(d.get("question", "")).strip()[:500]
    sequence = d.get("stroke_order", [])
    if not character or not question:
        return JsonResponse({"answer": "Enter a question about the character you’re practicing."}, status=400)
    if not os.environ.get("GEMINI_API_KEY"):
        return JsonResponse({"answer": "Gemini isn’t enabled. Set GEMINI_API_KEY in the server environment to ask questions."}, status=503)
    sequence_text = "\n".join(str(item)[:120] for item in sequence[:20]) if isinstance(sequence, list) else "Unavailable"
    prompt = (
        "You are a careful Chinese handwriting tutor. Answer the learner's question about this character's stroke order. "
        "Treat the supplied Hanzi Writer sequence as authoritative. Explain a character-specific reason only when you know one; "
        "do not invent etymology or a story. If there is no reliable special reason, say the order follows conventional stroke-order practice. "
        "In at most 3 short sentences, use plain English and refer to stroke numbers or directions when useful.\n\n"
        "Character: " + character + "\n"
        "Learner question: " + question + "\n"
        "Hanzi Writer stroke sequence (in order):\n" + sequence_text
    )
    answer, error = gemini_result(prompt)
    if not answer:
        return JsonResponse({"answer": error or "Gemini didn’t respond. Try again in a moment."}, status=502)
    return JsonResponse({"answer": answer})


def dashboard(request):
    user = request.GET.get("user", "guest")
    attempts = Attempt.objects.filter(user=user).order_by("-created")[:20]
    habits = habit_profile(user)
    chars, weak, focus = practice_for(user)
    return render(request, "coach/dashboard.html", {
        "user": user, "attempts": attempts, "habits": habits,
        "weak": weak, "plan": chars, "focus": focus,
        "total": Attempt.objects.filter(user=user).count(),
    })


@csrf_exempt
def api_tts(request):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return JsonResponse({"error": "tts off"}, status=503)
    d = json.loads(request.body)
    voice = os.environ.get("ELEVENLABS_VOICE", "21m00Tcm4TlvDq8ikWAM")
    url = "https://api.elevenlabs.io/v1/text-to-speech/" + voice
    body = json.dumps({"text": d.get("text", ""),
                       "model_id": "eleven_multilingual_v2"}).encode()
    headers = {"Content-Type": "application/json", "xi-api-key": key}
    req = urllib.request.Request(url, body, headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return HttpResponse(r.read(), content_type="audio/mpeg")
    except Exception as e:
        print("TTS error:", e)
        return JsonResponse({"error": "tts failed"}, status=502)
