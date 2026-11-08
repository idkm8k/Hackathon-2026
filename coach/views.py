import json, os, re, urllib.error, urllib.request
from collections import Counter
from django.db.models import Avg, Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Attempt, EnclosureChar, ExplanationCache, StrokeMistake
from .enclosure_rules import RULES, describe_roles, rule_for

STARTER = list("人大天口日月木水火山你好我他中国学书写永")
ENCLOSURE_ADDITIONS = list("口日目田回因国同问间区这进")
PRACTICE_POOL = list(dict.fromkeys(STARTER + ENCLOSURE_ADDITIONS))
ENCLOSURE_STRATEGIES = {
    "frame_before_contents": "trace the outside walls first, then fill the middle",
    "close_the_door_last": "leave the bottom closing stroke until the contents are in",
    "walk_radical_last": "finish the main character before adding the walking radical",
    "contents_before_cup": "draw the inside mark before the cup-shaped frame",
}


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


def enclosure_rule_profile(user):
    records = list(StrokeMistake.objects.filter(user=user).exclude(rule="").order_by("created"))
    family_by_character = dict(EnclosureChar.objects.filter(
        character__in={m.character for m in records}
    ).values_list("character", "family"))
    groups = {}
    for mistake in records:
        info = RULES.get(mistake.rule)
        if not info:
            continue
        group = groups.setdefault(mistake.rule, {
            "code": mistake.rule, "label": info["name"], "definition": info["definition"],
            "count": 0, "char_counts": Counter(), "family_counts": Counter(),
        })
        group["count"] += 1
        group["char_counts"][mistake.character] += 1
        family = family_by_character.get(mistake.character)
        if family:
            group["family_counts"][family] += 1
    profiles = []
    for group in groups.values():
        counts = group.pop("char_counts")
        families = group.pop("family_counts")
        group["characters"] = sorted(counts, key=lambda ch: (-counts[ch], ch))
        group["character_count"] = len(counts)
        group["recurring"] = len(counts) >= 2
        group["family"] = families.most_common(1)[0][0] if families else ""
        profiles.append(group)
    profiles.sort(key=lambda item: (-item["count"], -item["character_count"], item["code"]))
    return profiles


def enclosure_exceptions_unlocked(user):
    box_or_door = EnclosureChar.objects.filter(family__in=("box", "door")).values("character")
    return Attempt.objects.filter(
        user=user, character__in=box_or_door, completed=True, mistakes=0
    ).exists()


def practice_for(user, n=6):
    """Mix rule-targeted enclosure review with the existing general review plan."""
    habits = habit_profile(user)
    focus = habits[0] if habits else None
    rule_profiles = enclosure_rule_profile(user)
    rule_focus = rule_profiles[0] if rule_profiles else None
    seen = set(Attempt.objects.filter(user=user).values_list("character", flat=True))
    unlocked = enclosure_exceptions_unlocked(user)
    family_by_character = dict(EnclosureChar.objects.filter(
        character__in=PRACTICE_POOL
    ).values_list("character", "family"))
    eligible = {ch for ch in PRACTICE_POOL
                if unlocked or family_by_character.get(ch) not in ("walk", "cup")}
    rule_chars = [ch for ch in (rule_focus["characters"] if rule_focus else [])
                  if ch in eligible]
    family_candidates = []
    if rule_focus and rule_focus["family"]:
        family_candidates = list(EnclosureChar.objects.filter(
            family=rule_focus["family"], character__in=eligible
        ).exclude(character__in=seen).order_by("character").values_list("character", flat=True))
    stats = (Attempt.objects.filter(user=user).values("character")
             .annotate(avg=Avg("mistakes"), n=Count("id")).order_by("-avg"))
    weak_by_average = [s["character"] for s in stats if s["avg"] and s["avg"] > 0][:4]
    targeted = list(dict.fromkeys(rule_chars + (focus["characters"][:3] if focus else [])))
    weak = list(dict.fromkeys(targeted + weak_by_average))[:4]
    fresh = [c for c in PRACTICE_POOL if c in eligible and c not in seen]
    out = targeted + family_candidates
    out += [c for c in weak_by_average if c not in out]
    out += [c for c in fresh if c not in out]
    return out[:n], weak, focus, rule_focus


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
    chars, weak, focus, rule_focus = practice_for(user)
    seen = set(Attempt.objects.filter(user=user).values_list("character", flat=True))
    unlocked = enclosure_exceptions_unlocked(user)
    family_by_character = dict(EnclosureChar.objects.filter(
        character__in=PRACTICE_POOL
    ).values_list("character", "family"))
    candidates = [ch for ch in PRACTICE_POOL if ch not in seen
                  and (unlocked or family_by_character.get(ch) not in ("walk", "cup"))]
    return JsonResponse({"chars": chars, "weak": weak,
                         "habit": focus["label"] if focus else "",
                         "habit_code": focus["code"] if focus else "",
                         "habit_chars": focus["characters"] if focus else [],
                         "candidate_chars": candidates,
                         "recurring": focus["recurring"] if focus else False,
                         "enclosure_rule": rule_focus["code"] if rule_focus else "",
                         "enclosure_rule_name": rule_focus["label"] if rule_focus else "",
                         "enclosure_rule_chars": rule_focus["characters"] if rule_focus else [],
                         "enclosure_rule_recurring": rule_focus["recurring"] if rule_focus else False,
                         "enclosure_family": rule_focus["family"] if rule_focus else "",
                         "exceptions_unlocked": unlocked})


def enclosure_fallback(rule_code, characters):
    info = RULES[rule_code]
    text = "{}: {} Mnemonic: {}".format(info["name"], info["definition"], info["mnemonic"])
    if len(characters) >= 2:
        examples = " and ".join(characters) if len(characters) == 2 else ", ".join(characters[:-1]) + ", and " + characters[-1]
        strategy = ENCLOSURE_STRATEGIES.get(rule_code, "pause and check the frame before drawing the next stroke")
        text += " You’ve made this mistake in {}. Next, {}.".format(examples, strategy)
    return text


def enclosure_history(user, rule_code):
    records = list(StrokeMistake.objects.filter(user=user, rule=rule_code)
                   .order_by("created").values_list("character", flat=True))
    characters = list(dict.fromkeys(records))
    level = "first" if len(characters) < 2 else "repeat" if len(characters) == 2 else "chronic"
    signature = json.dumps({"characters": characters, "records": len(records)}, ensure_ascii=False)
    return records, characters, level, signature


def explain_enclosure(mistake):
    rule_code = mistake.rule
    info = RULES[rule_code]
    row = EnclosureChar.objects.filter(pk=mistake.character).first()
    expected_drawn = re.fullmatch(r"order_(\d+)_(\d+)", mistake.diagnosis)
    if not row or not expected_drawn:
        return {"explanation": enclosure_fallback(rule_code, [mistake.character]),
                "source": "rule", "rule": rule_code}
    expected, drawn = (int(value) for value in expected_drawn.groups())
    records, characters, level, signature = enclosure_history(mistake.user, rule_code)
    fallback = enclosure_fallback(rule_code, characters)
    cache = ExplanationCache.objects.filter(
        user=mistake.user, character=mistake.character, rule=rule_code, level=level
    ).first()
    key_available = bool(os.environ.get("GEMINI_API_KEY"))
    if cache and cache.history_signature == signature and (cache.source == "gemini" or not key_available):
        return {"explanation": cache.explanation, "source": "cache", "rule": rule_code, "level": level}

    history_text = ("{} diagnosed mistake record(s) across {} distinct character(s): {}".format(
        len(records), len(characters), "、".join(characters)) if characters else "No earlier learner history.")
    prompt = (
        "You are a concise Chinese handwriting coach. Explain only the single verified rule definition below. "
        "Use only the supplied rule definition, stroke roles, character, stroke numbers, and learner history. "
        "Do not mention etymology or any other rule. In no more than two short sentences, explain the mistake in plain English. "
        "Do not repeat the learner-history sentence; the app will add it when relevant.\n\n"
        "Verified rule definition: {}\n"
        "Verified stroke roles: {}\n"
        "Character: {}\n"
        "Stroke {} was expected; the learner drew stroke {} instead.\n"
        "Learner history for this same rule: {}"
    ).format(info["definition"], describe_roles({
        "pattern": row.pattern, "frame_component": row.frame_component,
    }), mistake.character, expected, drawn, history_text)
    explanation, _error = gemini_result(prompt) if key_available else (None, "")
    source = "gemini" if explanation else "rule"
    explanation = (explanation or fallback).strip()
    if source == "gemini":
        explanation = " ".join(re.split(r"(?<=[.!?])\s+", explanation.replace("\n", " ").strip())[:2])
    if len(characters) >= 2 and source == "gemini":
        examples = " and ".join(characters) if len(characters) == 2 else ", ".join(characters[:-1]) + ", and " + characters[-1]
        strategy = ENCLOSURE_STRATEGIES.get(rule_code, "pause and check the frame before drawing the next stroke")
        explanation += " You’ve made this mistake in {}. Next, {}.".format(examples, strategy)
    ExplanationCache.objects.update_or_create(
        user=mistake.user, character=mistake.character, rule=rule_code, level=level,
        defaults={"history_signature": signature, "explanation": explanation, "source": source},
    )
    mistake.explanation = explanation
    mistake.save(update_fields=["explanation"])
    return {"explanation": explanation, "source": source, "rule": rule_code, "level": level}


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
        rule_code = ""
        order = re.fullmatch(r"order_(\d+)_(\d+)", diagnosis)
        if order:
            row = EnclosureChar.objects.filter(pk=ch).values("family", "frame_component", "pattern").first()
            if row:
                candidate = rule_for(row, int(order.group(1)) - 1, int(order.group(2)) - 1)
                if candidate in RULES:
                    rule_code = candidate
        habit = m.get("habit", "")
        if rule_code or not re.fullmatch(
            r"(?:order_(?:horizontal|vertical|diagonal)_before_(?:horizontal|vertical|diagonal)|reversed_(horizontal|vertical|diagonal))",
            habit,
        ):
            habit = ""
        saved.append(StrokeMistake(
            attempt=a, user=user, character=ch,
            stroke_num=m["stroke"], board_size=m.get("size", 300),
            drawn_points=json.dumps(points), diagnosis=diagnosis, habit=habit, rule=rule_code))
    StrokeMistake.objects.bulk_create(saved)
    diagnosis = next((m.diagnosis for m in saved if m.diagnosis), "")
    rule_code = next((m.rule for m in saved if m.rule), "")
    explanation = ""
    if rule_code:
        _records, chars, _level, _signature = enclosure_history(user, rule_code)
        explanation = enclosure_fallback(rule_code, chars)
    return JsonResponse({"ok": True, "attempt_id": a.pk, "diagnosis": diagnosis,
                         "rule": rule_code, "rule_explanation": explanation})


@csrf_exempt
def api_explain(request):
    """Explain a stored diagnosis with verified enclosure rules or legacy feedback."""
    try:
        d = json.loads(request.body)
        attempt = Attempt.objects.get(pk=d.get("attempt_id"), user=d.get("user", "guest"))
    except (json.JSONDecodeError, Attempt.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"error": "Practice attempt not found."}, status=404)

    mistake = attempt.stroke_mistakes.exclude(diagnosis="").first()
    if not mistake:
        return JsonResponse({"explanation": "I couldn’t confidently identify the stroke-order rule from that drawing."})
    if mistake.rule in RULES:
        return JsonResponse(explain_enclosure(mistake))

    cached = StrokeMistake.objects.filter(
        user=mistake.user, character=mistake.character,
        diagnosis=mistake.diagnosis, habit=mistake.habit,
    ).exclude(explanation="").exclude(attempt=attempt).order_by("-created").first()
    if cached:
        mistake.explanation = cached.explanation
        mistake.save(update_fields=["explanation"])
        return JsonResponse({"explanation": cached.explanation, "source": "cache"})

    match = re.fullmatch(r"order_(\d+)_(\d+)", mistake.diagnosis)
    reverse = re.fullmatch(r"reversed_(\d+)", mistake.diagnosis)
    if match:
        expected, drawn = match.groups()
        verified = "Stroke {} was drawn before stroke {}.".format(drawn, expected)
    elif reverse:
        verified = "Stroke {} was drawn in the reverse direction.".format(reverse.group(1))
    else:
        verified = "The drawn stroke did not match the expected stroke path."

    history = []
    habit_label = ""
    if mistake.habit:
        profiles = habit_profile(mistake.user)
        profile = next((h for h in profiles if h["code"] == mistake.habit), None)
        if profile:
            habit_label = profile["label"]
            history = [{"character": h["character"], "stroke": h["stroke_num"]}
                       for h in StrokeMistake.objects.filter(
                           user=mistake.user, habit=mistake.habit
                       ).exclude(attempt=attempt).order_by("-created")[:8]]

    if not os.environ.get("GEMINI_API_KEY"):
        return JsonResponse({"explanation": verified, "source": "rule"})

    context = "The verified rule category is: {}.".format(habit_label or "specific stroke order/direction")
    prompt = (
        "You are a Chinese handwriting coach. Explain only the verified drawing diagnosis below. "
        "Do not infer a different rule, character etymology, or unsupported cultural mnemonic. "
        "Use the learner history only to mention a recurring pattern when it supports the same rule. "
        "In one or two short sentences, say why to change the stroke order or direction and give a simple memory cue. "
        "If the history has no examples, explain this attempt without claiming a recurring habit. "
        "Plain spoken English, no markdown or emojis.\n\n"
        "Character: {}\nVerified diagnosis: {}\n{}\nRelated saved history: {}"
    ).format(attempt.character, verified, context, json.dumps(history, ensure_ascii=False) if history else "none")
    explanation, _error = gemini_result(prompt)
    if explanation:
        mistake.explanation = explanation
        mistake.save(update_fields=["explanation"])
    return JsonResponse({"explanation": explanation or verified, "source": "gemini" if explanation else "rule"})


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
    chars, weak, focus, rule_focus = practice_for(user)
    return render(request, "coach/dashboard.html", {
        "user": user, "attempts": attempts, "habits": habits,
        "enclosure_rules": enclosure_rule_profile(user), "enclosure_focus": rule_focus,
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
