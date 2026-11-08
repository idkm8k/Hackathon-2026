from django.test import TestCase
from unittest.mock import patch
import json
import os

from .enclosure_rules import RULES, rule_for
from .models import Attempt, EnclosureChar, ExplanationCache, StrokeMistake


class EnclosureRuleIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        EnclosureChar.objects.bulk_create([
            EnclosureChar(character="日", family="box", frame_component="口", pattern="FFIC"),
            EnclosureChar(character="口", family="box", frame_component="囗", pattern="FFC"),
            EnclosureChar(character="目", family="box", frame_component="口", pattern="FFIIC"),
            EnclosureChar(character="田", family="box", frame_component="囗", pattern="FFIIC"),
            EnclosureChar(character="回", family="box", frame_component="囗", pattern="FFIIIC"),
            EnclosureChar(character="国", family="box", frame_component="囗", pattern="FFIIIIIC"),
            EnclosureChar(character="同", family="door", frame_component="冂", pattern="FFIIII"),
            EnclosureChar(character="这", family="walk", frame_component="辶", pattern="IIIIWWW"),
            EnclosureChar(character="进", family="walk", frame_component="辶", pattern="IIIIWWW"),
            EnclosureChar(character="凶", family="cup", frame_component="凵", pattern="IIWW"),
        ])

    def test_supplied_stroke_order_examples(self):
        cases = [
            ("日", "FFIC", "box", 3, 4, "close_the_door_last"),
            ("日", "FFIC", "box", 1, 3, "frame_before_contents"),
            ("国", "FFIIIIIC", "box", 1, 4, "frame_before_contents"),
            # The user message ended after the arrow; enclosure_rules.py supplies this expected result.
            ("国", "FFIIIIIC", "box", 3, 8, "close_the_door_last"),
        ]
        for character, pattern, family, expected, drawn, wanted in cases:
            with self.subTest(character=character, expected=expected, drawn=drawn):
                result = rule_for({"pattern": pattern, "family": family}, expected - 1, drawn - 1)
                self.assertEqual(result, wanted)
                self.assertIn(result, RULES)

    def test_other_enclosure_families_keep_their_verified_exceptions(self):
        cases = [
            ("口", "FFC", "box", 1, 3, "close_the_door_last"),
            ("田", "FFIIC", "box", 4, 5, "close_the_door_last"),
            ("回", "FFIIIC", "box", 2, 4, "frame_before_contents"),
            ("同", "FFIIII", "door", 2, 4, "frame_before_contents"),
            ("这", "IIIIWWW", "walk", 1, 5, "walk_radical_last"),
            ("凶", "IIWW", "cup", 1, 3, "contents_before_cup"),
        ]
        for character, pattern, family, expected, drawn, wanted in cases:
            with self.subTest(character=character):
                result = rule_for({"pattern": pattern, "family": family}, expected - 1, drawn - 1)
                self.assertEqual(result, wanted)
                self.assertIn(result, RULES)

    def test_api_log_stores_rule_and_suppresses_generic_habit_for_it(self):
        payload = {"user": "learner", "character": "日", "mistakes": [3], "completed": True,
                   "details": [{"stroke": 3, "size": 900, "points": [], "diagnosis": "order_3_4",
                                "habit": "order_vertical_before_horizontal"}]}
        response = self.client.post("/api/log/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["rule"], "close_the_door_last")
        self.assertIn("Close the door last", data["rule_explanation"])
        saved = StrokeMistake.objects.get(attempt_id=data["attempt_id"])
        self.assertEqual(saved.rule, "close_the_door_last")
        self.assertEqual(saved.habit, "")

    def test_unclassified_mistake_keeps_existing_habit_behavior(self):
        payload = {"user": "learner", "character": "日", "mistakes": [1], "completed": True,
                   "details": [{"stroke": 1, "points": [], "diagnosis": "order_1_2",
                                "habit": "order_vertical_before_horizontal"}]}
        response = self.client.post("/api/log/", data=json.dumps(payload), content_type="application/json")
        saved = StrokeMistake.objects.get(attempt_id=response.json()["attempt_id"])
        self.assertEqual(saved.rule, "")
        self.assertEqual(saved.habit, "order_vertical_before_horizontal")

    def test_fallback_is_safe_and_cached_without_gemini(self):
        log = self.client.post("/api/log/", data=json.dumps({
            "user": "learner", "character": "日", "mistakes": [3],
            "details": [{"stroke": 3, "points": [], "diagnosis": "order_3_4"}],
        }), content_type="application/json").json()
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post("/api/explain/", data=json.dumps({
                "user": "learner", "attempt_id": log["attempt_id"],
            }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Close the door last", response.json()["explanation"])
        self.assertIn(RULES["close_the_door_last"]["mnemonic"], response.json()["explanation"])
        self.assertEqual(response.json()["source"], "rule")
        self.assertEqual(ExplanationCache.objects.get().level, "first")

    def test_gemini_failure_uses_rule_fallback_without_error(self):
        log = self.client.post("/api/log/", data=json.dumps({
            "user": "learner", "character": "国", "mistakes": [3],
            "details": [{"stroke": 3, "points": [], "diagnosis": "order_3_8"}],
        }), content_type="application/json").json()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "coach.views.gemini_result", return_value=(None, "offline")
        ):
            response = self.client.post("/api/explain/", data=json.dumps({
                "user": "learner", "attempt_id": log["attempt_id"],
            }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("error", response.json())
        self.assertIn("Close the door last", response.json()["explanation"])
        self.assertIn(RULES["close_the_door_last"]["mnemonic"], response.json()["explanation"])

    def test_gemini_prompt_uses_verified_facts_and_repeat_feedback_is_cached(self):
        mistakes = []
        for ch, stroke, diagnosis in (("日", 3, "order_3_4"), ("田", 4, "order_4_5"), ("国", 3, "order_3_4")):
            attempt = Attempt.objects.create(user="learner", character=ch, mistakes=1, completed=True)
            mistakes.append(StrokeMistake.objects.create(
                attempt=attempt, user="learner", character=ch, stroke_num=stroke,
                diagnosis=diagnosis, rule="close_the_door_last"))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "coach.views.gemini_result", return_value=("Leave the lower wall for last.", "")
        ) as gemini:
            payload = json.dumps({"user": "learner", "attempt_id": mistakes[-1].attempt_id})
            first = self.client.post("/api/explain/", data=payload, content_type="application/json").json()
            second = self.client.post("/api/explain/", data=payload, content_type="application/json").json()
        self.assertEqual(first["level"], "chronic")
        self.assertIn("日, 田, and 国", first["explanation"])
        self.assertIn("leave the bottom closing stroke", first["explanation"])
        self.assertEqual(second["source"], "cache")
        self.assertEqual(gemini.call_count, 1)
        prompt = gemini.call_args.args[0]
        self.assertIn(RULES["close_the_door_last"]["definition"], prompt)
        self.assertIn("stroke(s) 8: closing stroke", prompt)
        self.assertIn("expected; the learner drew stroke", prompt)
        self.assertIn("learner history for this same rule", prompt.lower())

    def test_practice_picker_targets_family_and_gates_exceptions_until_success(self):
        attempt = Attempt.objects.create(user="learner", character="日", mistakes=1, completed=True)
        StrokeMistake.objects.create(attempt=attempt, user="learner", character="日",
                                     stroke_num=3, diagnosis="order_3_4", rule="close_the_door_last")
        before = self.client.get("/api/practice/?user=learner").json()
        self.assertEqual(before["enclosure_family"], "box")
        self.assertNotIn("这", before["candidate_chars"])
        self.assertNotIn("进", before["candidate_chars"])
        self.assertTrue(any(ch in {"口", "目", "田", "回", "国"} for ch in before["chars"]))
        Attempt.objects.create(user="learner", character="同", mistakes=0, completed=True)
        after = self.client.get("/api/practice/?user=learner").json()
        self.assertTrue(after["exceptions_unlocked"])
        self.assertIn("这", after["candidate_chars"])
        self.assertIn("进", after["candidate_chars"])

    def test_dashboard_displays_rule_name_and_character(self):
        attempt = Attempt.objects.create(user="learner", character="日", mistakes=1, completed=True)
        StrokeMistake.objects.create(attempt=attempt, user="learner", character="日",
                                     stroke_num=3, diagnosis="order_3_4", rule="close_the_door_last")
        response = self.client.get("/dashboard/?user=learner")
        self.assertContains(response, "Close the door last")
        self.assertContains(response, "日")


class HeadsUpEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        EnclosureChar.objects.bulk_create([
            EnclosureChar(character="日", family="box", frame_component="口", pattern="FFIC"),
            EnclosureChar(character="田", family="box", frame_component="囗", pattern="FFIIC"),
            EnclosureChar(character="国", family="box", frame_component="囗", pattern="FFIIIIIC"),
            EnclosureChar(character="这", family="walk", frame_component="辶", pattern="IIIIWWW"),
            EnclosureChar(character="凶", family="cup", frame_component="凵", pattern="IIWW"),
        ])

    def add_rule_mistake(self, user, character, rule):
        attempt = Attempt.objects.create(user=user, character=character, mistakes=1, completed=True)
        return StrokeMistake.objects.create(
            attempt=attempt, user=user, character=character,
            stroke_num=1, diagnosis="order_1_2", rule=rule,
        )

    def test_returns_most_frequent_applicable_rule_and_learner_characters(self):
        self.add_rule_mistake("learner", "日", "frame_before_contents")
        self.add_rule_mistake("learner", "田", "close_the_door_last")
        self.add_rule_mistake("learner", "国", "close_the_door_last")
        self.add_rule_mistake("someone-else", "田", "close_the_door_last")
        response = self.client.get("/api/heads_up/?user=learner&character=日")
        self.assertEqual(response.status_code, 200)
        result = response.json()["heads_up"]
        self.assertEqual(result["rule"], "close_the_door_last")
        self.assertEqual(result["name"], RULES["close_the_door_last"]["name"])
        self.assertEqual(result["mnemonic"], RULES["close_the_door_last"]["mnemonic"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["characters"], ["田", "国"])

    def test_no_matching_history_or_unknown_character_returns_nothing(self):
        response = self.client.get("/api/heads_up/?user=learner&character=日")
        self.assertIsNone(response.json()["heads_up"])
        response = self.client.get("/api/heads_up/?user=learner&character=未")
        self.assertIsNone(response.json()["heads_up"])

    def test_walk_and_cup_patterns_select_their_exception_rule(self):
        self.add_rule_mistake("learner", "这", "walk_radical_last")
        self.add_rule_mistake("learner", "凶", "contents_before_cup")
        walk = self.client.get("/api/heads_up/?user=learner&character=这").json()["heads_up"]
        cup = self.client.get("/api/heads_up/?user=learner&character=凶").json()["heads_up"]
        self.assertEqual(walk["rule"], "walk_radical_last")
        self.assertEqual(cup["rule"], "contents_before_cup")

    def test_correct_and_mistaken_paths_are_saved_in_replay_order(self):
        payload = {
            "user": "learner", "character": "日", "mistakes": [3],
            "details": [{"stroke": 3, "points": [[100, 200], [200, 200]], "diagnosis": "order_3_4"}],
            "replay": [
                {"stroke": 3, "correct": False, "size": 900,
                 "points": [[100, 200], [200, 200]], "diagnosis": "order_3_4"},
                {"stroke": 3, "correct": True, "size": 900,
                 "points": [[101, 201], [202, 201]]},
            ],
        }
        response = self.client.post("/api/log/", data=json.dumps(payload), content_type="application/json")
        attempt_id = response.json()["attempt_id"]
        traces = list(Attempt.objects.get(pk=attempt_id).stroke_traces.all())
        self.assertEqual([trace.correct for trace in traces], [False, True])
        self.assertEqual(json.loads(traces[0].drawn_points), [[100, 200], [200, 200]])
        replay = self.client.get("/replay/{}/?user=learner".format(attempt_id))
        self.assertEqual(replay.status_code, 200)
        self.assertContains(replay, "replay-events")
