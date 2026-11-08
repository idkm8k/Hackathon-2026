"""
Outside-before-inside rule family for Hanzi Coach.

Pipeline:  Make Me a Hanzi dictionary.txt  ->  per-stroke roles  ->  curated whitelist
           ->  hand overrides  ->  rule_for(character, expected_stroke, drawn_stroke)

Each enclosure character gets a PATTERN: one letter per stroke, in standard order.
    F = part of the outer frame, drawn before the contents
    I = contents inside the frame
    C = the closing stroke, drawn last ("shut the door")
    W = a frame that is drawn LAST on purpose (the 辶 / 廴 "walking" radicals, 凵 cup)
Example:  日 = FFIC   国 = FFIIIIIC   同 = FFFIII   这 = IIIIWWW

Usage:
    python enclosure_rules.py dictionary.txt            # self-test
    python enclosure_rules.py dictionary.txt --build    # writes enclosures.json (Django fixture-ready)
"""
import json, re, sys

# --------------------------------------------------------------------------
# 1. The curated knowledge: which frame components get which treatment.
#    THIS is the part that is yours. Other apps have stroke data, not this.
# --------------------------------------------------------------------------
FAMILY_BY_COMPONENT = {
    "囗": "box", "口": "box",             # 国 回 因 四 / 日 目 (decomposed with 口)
    "冂": "door", "门": "door", "凡": "door",   # 同 冈 问 间
    "匚": "side_box", "匸": "side_box",   # 区 医 匠
    "广": "roof", "尸": "roof", "疒": "roof", "厂": "roof",   # 床 屋 病 历
    "勹": "roof",                         # 包 句
    "辶": "walk", "廴": "walk",           # 这 进 道 建
    "凵": "cup",                          # 凶
}

# Hand overrides where the source decomposition disagrees with how it is taught.
# pattern is given directly; None = exclude from this rule family.
OVERRIDES = {
    "口": ("box", "囗", "FFC"),        # left, top+right, bottom last
    "田": ("box", "囗", "FFIIC"),      # dictionary assigns the bottom stroke to 土
    "同": ("door", "冂", "FFIIII"),    # dictionary wrongly puts stroke 3 in the frame
    "山": None,                        # center-before-sides, a different rule
    "勉": None, "处": None,            # taught left-to-right, not as enclosures
}

# --------------------------------------------------------------------------
# 2. The rules (these definitions are what Gemini is allowed to explain)
# --------------------------------------------------------------------------
RULES = {
    "frame_before_contents": {
        "name": "Outside before inside",
        "definition": "When a character has an outer frame, write the frame's walls first, then what goes inside.",
        "mnemonic": "Build the house first, then move the furniture in.",
    },
    "close_the_door_last": {
        "name": "Close the door last",
        "definition": "In a fully enclosed shape, write the left and top-right walls, then the contents, and close the bottom stroke last.",
        "mnemonic": "Let the person in, then shut the door.",
    },
    "walk_radical_last": {
        "name": "The walking radical goes last",
        "definition": "The 辶 and 廴 pieces at the bottom-left are an exception: write everything they sit under first, then the 辶 or 廴.",
        "mnemonic": "Lay the road last, after what travels on it.",
    },
    "contents_before_cup": {
        "name": "Fill the cup first",
        "definition": "In 凶, the exception to outside-before-inside: write the inner 乂 first, then the cup 凵 around it.",
        "mnemonic": "Fill the cup, then draw it.",
    },
}

# --------------------------------------------------------------------------
# 3. Build patterns from the dictionary
# --------------------------------------------------------------------------
SURROUND_OPS = set("⿴⿵⿶⿷⿸⿹⿺")

def load_dictionary(path):
    out = {}
    with open(path, encoding="utf8") as f:
        for line in f:
            r = json.loads(line)
            out[r["character"]] = r
    return out

def derive_pattern(entry):
    """Return (family, frame_component, pattern) or None."""
    dec, m = entry.get("decomposition", ""), entry.get("matches")
    if not dec or not m or dec[0] not in SURROUND_OPS or len(dec) < 2:
        return None
    if any(x is None or len(x) == 0 for x in m):
        return None
    comp = dec[1]
    family = FAMILY_BY_COMPONENT.get(comp)
    if not family:
        return None
    frame = [i for i, p in enumerate(m) if p[0] == 0]
    inner = [i for i in range(len(m)) if i not in frame]
    if not frame or not inner:
        return None
    first_inner, last_inner = min(inner), max(inner)
    letters = []
    for i in range(len(m)):
        if i in inner:
            letters.append("I")
        elif i < first_inner:
            letters.append("F")
        else:  # frame stroke after the contents
            letters.append("W" if family in ("walk", "cup") else "C")
    pattern = "".join(letters)
    # roof / door families have no closing stroke by convention
    if family in ("door", "roof"):
        pattern = pattern.replace("C", "F")
    return family, comp, pattern

def build_table(dictionary):
    table = {}
    for ch, entry in dictionary.items():
        if ch in OVERRIDES:
            if OVERRIDES[ch] is not None:
                fam, comp, pat = OVERRIDES[ch]
                table[ch] = {"family": fam, "frame_component": comp, "pattern": pat}
            continue
        d = derive_pattern(entry)
        if d:
            table[ch] = {"family": d[0], "frame_component": d[1], "pattern": d[2]}
    return table

# --------------------------------------------------------------------------
# 4. The classifier: which rule did this order mistake break?
#    expected / drawn are 0-indexed stroke numbers (drawn > expected).
# --------------------------------------------------------------------------
def rule_for(row, expected, drawn):
    """row = table entry for the character. Returns a rule code or ''."""
    p = row["pattern"]
    if not (0 <= expected < drawn < len(p)):
        return ""
    e, d = p[expected], p[drawn]
    if d == "C":                       # closed the door before walls/contents were done
        return "close_the_door_last"
    if e == "F" and d == "I":          # drew inside before finishing the frame
        return "frame_before_contents"
    if e == "I" and d == "W":          # applied the normal rule where it does not apply
        return "contents_before_cup" if row["family"] == "cup" else "walk_radical_last"
    return ""

# --------------------------------------------------------------------------
# 5. Words for the prompt: deterministic description of the roles, no guessing
# --------------------------------------------------------------------------
def describe_roles(row):
    p = row["pattern"]
    def span(letter):
        idx = [i + 1 for i, c in enumerate(p) if c == letter]
        if not idx: return ""
        return str(idx[0]) if len(idx) == 1 else f"{idx[0]}-{idx[-1]}"
    parts = []
    for letter, label in (("F", "outer frame"), ("I", "contents inside the frame"),
                          ("C", "closing stroke (written last)"), ("W", "frame written last on purpose")):
        s = span(letter)
        if s: parts.append(f"stroke(s) {s}: {label}")
    return f"Frame component {row['frame_component']}. " + "; ".join(parts) + "."

# --------------------------------------------------------------------------
if __name__ == "__main__":
    D = load_dictionary(sys.argv[1])
    T = build_table(D)
    if "--build" in sys.argv:
        fixture = [{"model": "coach.enclosurechar", "pk": ch, "fields": v} for ch, v in T.items()]
        json.dump(fixture, open("enclosures.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
        print("wrote enclosures.json with", len(fixture), "characters")
        sys.exit()

    from collections import Counter
    print("characters in table:", len(T), Counter(v["family"] for v in T.values()))
    print()
    tests = [  # (char, expected_stroke_1indexed, drawn_stroke_1indexed, what we expect)
        ("日", 3, 4, "close_the_door_last"),
        ("日", 1, 3, "frame_before_contents"),
        ("国", 1, 4, "frame_before_contents"),
        ("国", 3, 8, "close_the_door_last"),
        ("口", 1, 3, "close_the_door_last"),
        ("田", 4, 5, "close_the_door_last"),
        ("回", 2, 4, "frame_before_contents"),
        ("同", 2, 4, "frame_before_contents"),
        ("问", 3, 5, "frame_before_contents"),
        ("区", 1, 2, "frame_before_contents"),
        ("这", 1, 5, "walk_radical_last"),
        ("进", 2, 6, "walk_radical_last"),
        ("建", 1, 8, "walk_radical_last"),
        ("凶", 1, 3, "contents_before_cup"),
        ("日", 3, 3, ""),      # not an error
        ("山", 1, 2, "KeyError-expected"),   # excluded on purpose
    ]
    ok = True
    for ch, e, d, want in tests:
        if ch not in T:
            got = "KeyError-expected"
        else:
            got = rule_for(T[ch], e - 1, d - 1)
        flag = "ok " if got == want else "BAD"
        ok &= got == want
        pat = T[ch]["pattern"] if ch in T else "-"
        print(f"{flag} {ch} {pat:<12} expected stroke {e}, drew {d} -> {got or '(no enclosure rule)'}")
    print("\nroles for 国:", describe_roles(T["国"]))
    print("roles for 这:", describe_roles(T["这"]))
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
