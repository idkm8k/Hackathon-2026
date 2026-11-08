import json, os, re, urllib.request
from collections import Counter
from django.db.models import Avg, Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Attempt, StrokeMistake

STARTER = list("人大天口日月木水火山你好我他中国学书写永")


def habit_profile(user):
    """Summarize only diagnosed order/direction issues across characters."""
    groups = {
        "order": {"kind": "order", "label": "Stroke order", "count": 0,
                  "char_counts": Counter(), "examples": []},
        "direction": {"kind": "direction", "label": "Stroke direction", "count": 0,
                      "char_counts": Counter(), "examples": []},
    }
    records = (StrokeMistake.objects.filter(user=user).exclude(diagnosis="")
               .order_by("-created"))
    for mistake in records:
        match = re.fullmatch(r"order_([1-9]\d{0,2})_([1-9]\d{0,2})", mistake.diagnosis)
        if match:
            kind = "order"
            detail = "Drew stroke {} before stroke {}".format(match.group(2), match.group(1))
        else:
            match = re.fullmatch(r"reversed_([1-9]\d{0,2})", mistake.diagnosis)
            if not match:
                continue
            kind = "direction"
            detail = "Reversed stroke {}".format(match.group(1))
        group = groups[kind]
        group["count"] += 1
        group["char_counts"][mistake.character] += 1
        if len(group["examples"]) < 3:
            group["examples"].append({"character": mistake.character, "detail": detail})
    habits = []
    for kind in ("order", "direction"):
        group = groups[kind]
        # Preserve useful character names and prioritize those seen most often.
        counts = group.pop("char_counts")
        group["characters"] = sorted(counts, key=lambda ch: (-counts[ch], ch))
        group["character_count"] = len(counts)
        group["recurring"] = len(counts) >= 2
        if group["count"]:
            habits.append(group)
    habits.sort(key=lambda h: (not h["recurring"], -h["character_count"], -h["count"]))
    return habits


def practice_for(user, n=6):
    """Review characters tied to the user's strongest diagnosed habit first."""
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


def gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":generateContent")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    req = urllib.request.Request(url, body, headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.load(r)
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print("Gemini error:", e)
        return None


def index(request):
    return render(request, "coach/index.html")


def api_practice(request):
    user = request.GET.get("user", "guest")
    chars, weak, focus = practice_for(user)
    return JsonResponse({"chars": chars, "weak": weak,
                         "habit": focus["label"] if focus else "",
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
        saved.append(StrokeMistake(
            attempt=a, user=user, character=ch,
            stroke_num=m["stroke"], board_size=m.get("size", 300),
            drawn_points=json.dumps(points), diagnosis=diagnosis))
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
