import csv
import tempfile
import unittest
from pathlib import Path

from automated_scene_generator import (
    SceneGenerator,
    append_rows_dynamic_csv,
    build_bucket_summary,
    classify_intervention_bucket,
    determine_skip_outcome,
    flatten_record_for_csv,
    format_previous_shot_context,
)


class TestNonCarlaFunctions(unittest.TestCase):
    def test_bucket_classification(self):
        self.assertEqual(classify_intervention_bucket(0), "no_human_intervention")
        self.assertEqual(classify_intervention_bucket(1), "two_shot_or_one_intervention")
        self.assertEqual(classify_intervention_bucket(2), "multishot_or_multi_intervention")

    def test_build_bucket_summary(self):
        records = [
            {"tested": True, "intervention_count": 0, "final_success": True},
            {"tested": True, "intervention_count": 1, "final_success": False},
            {"tested": True, "intervention_count": 3, "final_success": True},
            {"tested": False, "intervention_count": 0, "final_success": False},
        ]
        summary = build_bucket_summary(records)

        self.assertEqual(summary["totals"]["tested"], 3)
        self.assertEqual(summary["totals"]["success"], 2)
        self.assertEqual(summary["totals"]["fail"], 1)

        self.assertEqual(summary["buckets"]["no_human_intervention"]["tested"], 1)
        self.assertEqual(summary["buckets"]["two_shot_or_one_intervention"]["tested"], 1)
        self.assertEqual(summary["buckets"]["multishot_or_multi_intervention"]["tested"], 1)

    def test_determine_skip_outcome(self):
        existing = determine_skip_outcome(True)
        self.assertTrue(existing["tested"])
        self.assertTrue(existing["final_success"])
        self.assertTrue(existing["skip_counted_as_pass"])

        fresh = determine_skip_outcome(False)
        self.assertFalse(fresh["tested"])
        self.assertTrue(fresh["excluded_from_tested"])
        self.assertFalse(fresh["final_success"])

    def test_dynamic_csv_header_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "scenario_intervention_data.csv"

            append_rows_dynamic_csv(
                csv_path,
                [
                    {
                        "scenario_keyword": "s1",
                        "shot_0_prompt_text": "base prompt",
                        "shot_0_code_file": "code0.py",
                    }
                ],
            )
            append_rows_dynamic_csv(
                csv_path,
                [
                    {
                        "scenario_keyword": "s2",
                        "shot_0_prompt_text": "base prompt 2",
                        "shot_1_prompt_text": "fix prompt",
                        "shot_1_code_file": "code1.py",
                    }
                ],
            )

            with open(csv_path, "r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                headers = reader.fieldnames or []

            self.assertIn("shot_1_prompt_text", headers)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["shot_1_prompt_text"], "")
            self.assertEqual(rows[1]["shot_1_prompt_text"], "fix prompt")

    def test_flatten_record_for_csv_wide_shots(self):
        record = {
            "run_id": "r1",
            "timestamp": "2026-02-03T00:00:00",
            "execution_mode": "interactive",
            "scene_keyword": "Red Light",
            "scenario_keyword": "red_light",
            "tested": True,
            "excluded_from_tested": False,
            "intervention_count": 1,
            "fix_rounds": 1,
            "llm_generation_count": 3,
            "sim_runs": 2,
            "final_success": True,
            "final_bucket": "two_shot_or_one_intervention",
            "final_status": "SUCCESS",
            "shot_artifacts": [
                {
                    "shot_index": 0,
                    "prompt_text": "base",
                    "prompt_file": "p0.txt",
                    "full_prompt_file": "fp0.txt",
                    "code_file": "c0.py",
                    "scene_output_dir": "o0",
                    "status": "needs_fix",
                },
                {
                    "shot_index": 1,
                    "prompt_text": "fix",
                    "user_adjustment_prompt": "car turns left",
                    "prompt_file": "p1.txt",
                    "full_prompt_file": "fp1.txt",
                    "code_file": "c1.py",
                    "scene_output_dir": "o1",
                    "status": "passed",
                },
            ],
        }

        row = flatten_record_for_csv(record)
        self.assertEqual(row["shot_0_prompt_text"], "base")
        self.assertEqual(row["shot_1_prompt_text"], "fix")
        self.assertEqual(row["shot_1_user_adjustment_prompt"], "car turns left")

    def test_format_previous_shot_context(self):
        context = format_previous_shot_context(
            {
                "shot_index": 2,
                "prompt_file": "/tmp/prompt.txt",
                "prompt_text": "add pedestrian",
                "user_adjustment_prompt": "car speed too high",
            }
        )
        self.assertIn("shot_2", context)
        self.assertIn("car speed too high", context)

    def test_fix_prompt_includes_history(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        prompt = SceneGenerator.build_fix_prompt_context(
            generator,
            scenario_keyword="red_light",
            enhanced_prompt="Base prompt",
            issues="Vehicle ignores red signal",
            current_code="print('hi')",
            shot_history=[
                {
                    "shot_index": 0,
                    "prompt_file": "p0.txt",
                    "prompt_text": "base",
                    "sim_success": False,
                    "frames_ok": True,
                    "status": "needs_fix",
                },
                {
                    "shot_index": 1,
                    "prompt_file": "p1.txt",
                    "prompt_text": "fix1",
                    "user_adjustment_prompt": "red light handling wrong",
                    "sim_success": False,
                    "frames_ok": False,
                    "status": "failed_runtime_or_frames",
                },
            ],
        )

        self.assertIn("PREVIOUS SHOTS", prompt)
        self.assertIn("SHOT 0", prompt)
        self.assertIn("SHOT 1", prompt)
        self.assertIn("red light handling wrong", prompt)
        self.assertIn("MUST-FIX CHECKLIST", prompt)
        self.assertIn("DO-NOT-REPEAT FAILURES FROM PRIOR SHOTS", prompt)
        self.assertIn("Address every MUST-FIX checklist item", prompt)

    def test_build_shot_feedback_log_lines_includes_previous_adjustments(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        lines = SceneGenerator._build_shot_feedback_log_lines(
            generator,
            [
                {
                    "shot_index": 0,
                    "status": "needs_fix",
                    "sim_success": False,
                    "frames_ok": True,
                    "prompt_text": "base prompt with no pedestrian crossing",
                },
                {
                    "shot_index": 1,
                    "status": "needs_fix",
                    "sim_success": False,
                    "frames_ok": True,
                    "user_adjustment_prompt": "pedestrian must cross in front in first few seconds",
                },
            ],
        )

        self.assertEqual(len(lines), 2)
        self.assertIn("shot_1", lines[1])
        self.assertIn("user_adjustment=", lines[1])
        self.assertIn("pedestrian must cross in front", lines[1])

    def test_generate_code_with_token_retry_when_missing_main(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        call_counts = {"count": 0}
        responses = [
            "```python\nprint('hi')\n```",
            "```python\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n```",
        ]

        class DummyResponse:
            def __init__(self, text: str) -> None:
                self.content = [type("Content", (), {"text": text})()]

        def fake_call(*_args, **_kwargs):
            call_counts["count"] += 1
            return DummyResponse(responses.pop(0))

        generator._call_claude_api = fake_call

        result = SceneGenerator._generate_code_with_token_retry(
            generator,
            messages=[{"role": "user", "content": "code please"}],
            base_max_tokens=10,
            retry_max_tokens=20,
            context_label="unit-test",
        )

        self.assertIn("def main", result)
        self.assertEqual(call_counts["count"], 2)

    def test_shot_paths_are_run_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            generator = SceneGenerator.__new__(SceneGenerator)
            generator.prompts_dir = Path(tmp) / "generated_prompts"
            generator.code_dir = Path(tmp) / "generated_code"
            generator.scenes_dir = Path(tmp) / "scenes"
            generator.run_id = "20260203_123000"

            paths = SceneGenerator._shot_paths(generator, "red_light", 1)

            self.assertTrue(paths["prompt_file"].exists() is False)
            self.assertTrue(paths["prompt_dir"].exists())
            self.assertIn("shot_1", str(paths["prompt_dir"]))
            self.assertIn("20260203_123000", str(paths["code_dir"]))

    def test_verify_frames_accepts_when_at_least_50_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene_output = Path(tmp) / "scene"
            scene_output.mkdir(parents=True, exist_ok=True)

            # 20s run => expected 400 frames at 20 FPS; create exactly 200 frames (50%)
            for i in range(200):
                (scene_output / f"frame_{i:06d}.png").write_text("", encoding="utf-8")

            generator = SceneGenerator.__new__(SceneGenerator)
            result = SceneGenerator.verify_frames(
                generator, scene_output, duration_seconds=20, min_success_ratio=0.5
            )
            self.assertTrue(result)

    def test_verify_frames_rejects_below_50_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene_output = Path(tmp) / "scene"
            scene_output.mkdir(parents=True, exist_ok=True)

            # 20s run => expected 400 frames; create 199 (<50%)
            for i in range(199):
                (scene_output / f"frame_{i:06d}.png").write_text("", encoding="utf-8")

            generator = SceneGenerator.__new__(SceneGenerator)
            result = SceneGenerator.verify_frames(
                generator, scene_output, duration_seconds=20, min_success_ratio=0.5
            )
            self.assertFalse(result)

    def test_process_scene_autonomous_ignores_runtime_error_when_frames_ok(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        generator.generate_only = False
        generator.execution_mode = "autonomous"
        generator.max_attempts = 1
        generator.test_mode = True
        generator.run_id = "run1"

        generator.find_existing_assets = lambda _k: {
            "has_assets": False,
            "latest_code": None,
            "latest_prompt": None,
        }
        generator.generate_initial_shot = lambda _scene, scenario_keyword: (
            {
                "shot_index": 0,
                "prompt_text": "base prompt",
                "user_adjustment_prompt": "",
                "prompt_file": "p0.txt",
                "full_prompt_file": "fp0.txt",
                "code_file": f"{scenario_keyword}.py",
                "scene_output_dir": "out0",
                "sim_success": "",
                "frames_ok": "",
                "accepted_by_user": "",
                "status": "generated",
                "timestamp": "2026-02-05T00:00:00",
            },
            "enhanced prompt",
            2,
        )
        generator.run_simulation = lambda **_kwargs: (False, "timeout")
        generator.verify_frames = lambda *_args, **_kwargs: True
        generator.generate_fix_shot = lambda **_kwargs: None
        generator.ask_rerun_simulation = lambda: "continue"

        record = SceneGenerator.process_scene(
            generator, {"keyword": "Red Light", "prompt": "red light violation"}
        )

        self.assertTrue(record["final_success"])
        self.assertEqual(record["final_status"], "SUCCESS")
        self.assertEqual(record["shot_artifacts"][0]["accepted_by_user"], "autonomous")

    def test_process_scene_interactive_goes_to_feedback_when_frames_ok(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        generator.generate_only = False
        generator.execution_mode = "interactive"
        generator.max_attempts = 1
        generator.test_mode = True
        generator.run_id = "run2"

        generator.find_existing_assets = lambda _k: {
            "has_assets": False,
            "latest_code": None,
            "latest_prompt": None,
        }
        generator.generate_initial_shot = lambda _scene, scenario_keyword: (
            {
                "shot_index": 0,
                "prompt_text": "base prompt",
                "user_adjustment_prompt": "",
                "prompt_file": "p0.txt",
                "full_prompt_file": "fp0.txt",
                "code_file": f"{scenario_keyword}.py",
                "scene_output_dir": "out0",
                "sim_success": "",
                "frames_ok": "",
                "accepted_by_user": "",
                "status": "generated",
                "timestamp": "2026-02-05T00:00:00",
            },
            "enhanced prompt",
            2,
        )
        generator.run_simulation = lambda **_kwargs: (False, "runtime error")
        generator.verify_frames = lambda *_args, **_kwargs: True
        generator.get_user_feedback = lambda **_kwargs: {
            "accepted": True,
            "issues": "",
            "skip": False,
        }
        generator.generate_fix_shot = lambda **_kwargs: None
        generator.ask_rerun_simulation = lambda: "continue"

        record = SceneGenerator.process_scene(
            generator, {"keyword": "Red Light", "prompt": "red light violation"}
        )

        self.assertTrue(record["final_success"])
        self.assertEqual(record["final_status"], "SUCCESS")
        self.assertTrue(record["shot_artifacts"][0]["accepted_by_user"])

    def test_compile_auto_issues_includes_log_excerpt_and_user_feedback(self):
        issues = SceneGenerator.compile_auto_issues(
            runtime_error="NameError: missing symbol",
            frames_ok=False,
            simulation_log_excerpt="[WARNING] lane invasion",
            user_feedback="ego car did not yield",
        )

        self.assertIn("RUNTIME/COMPILATION ISSUE DETECTED", issues)
        self.assertIn("FRAME VERIFICATION FAILED", issues)
        self.assertIn("SIMULATION LOG EXCERPT", issues)
        self.assertIn("[WARNING] lane invasion", issues)
        self.assertIn("USER FEEDBACK FOR THIS CONTINUE-AND-FIX ATTEMPT", issues)
        self.assertIn("ego car did not yield", issues)

    def test_process_scene_interactive_continue_passes_feedback_and_logs_to_fix_prompt(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        generator.generate_only = False
        generator.execution_mode = "interactive"
        generator.max_attempts = 1
        generator.test_mode = True
        generator.run_id = "run3"

        generator.find_existing_assets = lambda _k: {
            "has_assets": False,
            "latest_code": None,
            "latest_prompt": None,
        }
        generator.generate_initial_shot = lambda _scene, scenario_keyword: (
            {
                "shot_index": 0,
                "prompt_text": "base prompt",
                "user_adjustment_prompt": "",
                "prompt_file": "p0.txt",
                "full_prompt_file": "fp0.txt",
                "code_file": f"{scenario_keyword}.py",
                "scene_output_dir": "out0",
                "sim_success": "",
                "frames_ok": "",
                "accepted_by_user": "",
                "status": "generated",
                "timestamp": "2026-02-05T00:00:00",
            },
            "enhanced prompt",
            2,
        )
        generator.run_simulation = lambda **_kwargs: (False, "NameError: missing symbol")
        generator.verify_frames = lambda *_args, **_kwargs: False
        generator.ask_rerun_simulation = lambda: "continue"
        generator.ask_continue_feedback_for_fix = lambda _err: "ego car did not yield"
        generator.get_simulation_log_excerpt = lambda _dir: "[WARNING] lane invasion"

        captured = {}

        def fake_generate_fix_shot(**kwargs):
            captured.update(kwargs)
            return None

        generator.generate_fix_shot = fake_generate_fix_shot

        record = SceneGenerator.process_scene(
            generator, {"keyword": "Red Light", "prompt": "red light violation"}
        )

        self.assertEqual(captured["user_adjustment_prompt"], "ego car did not yield")
        self.assertIn("SIMULATION LOG EXCERPT", captured["issues"])
        self.assertIn("[WARNING] lane invasion", captured["issues"])
        self.assertIn("NameError: missing symbol", captured["issues"])
        self.assertIn("ego car did not yield", captured["issues"])
        self.assertEqual(record["fix_rounds"], 1)
        self.assertEqual(record["final_status"], "FAILED")

    def test_failure_continue_reuses_same_shot_index(self):
        generator = SceneGenerator.__new__(SceneGenerator)
        generator.generate_only = False
        generator.execution_mode = "interactive"
        generator.max_attempts = 1
        generator.test_mode = True
        generator.run_id = "run4"

        generator.find_existing_assets = lambda _k: {
            "has_assets": False,
            "latest_code": None,
            "latest_prompt": None,
        }
        generator.generate_initial_shot = lambda _scene, scenario_keyword: (
            {
                "shot_index": 0,
                "prompt_text": "base prompt",
                "user_adjustment_prompt": "",
                "prompt_file": "p0.txt",
                "full_prompt_file": "fp0.txt",
                "code_file": f"{scenario_keyword}.py",
                "scene_output_dir": "out0",
                "sim_success": "",
                "frames_ok": "",
                "accepted_by_user": "",
                "status": "generated",
                "timestamp": "2026-02-05T00:00:00",
            },
            "enhanced prompt",
            1,
        )
        generator.run_simulation = lambda **_kwargs: (False, "NameError: missing symbol")
        generator.verify_frames = lambda *_args, **_kwargs: False
        generator.ask_rerun_simulation = lambda: "continue"
        generator.ask_continue_feedback_for_fix = lambda _err: "fix code error"
        generator.get_simulation_log_excerpt = lambda _dir: ""

        captured = {}

        def fake_generate_fix_shot(**kwargs):
            captured["next_shot_index"] = kwargs["next_shot_index"]
            return {
                "shot_index": kwargs["next_shot_index"],
                "prompt_text": "fix prompt",
                "user_adjustment_prompt": kwargs.get("user_adjustment_prompt", ""),
                "prompt_file": "p0_fix.txt",
                "full_prompt_file": "fp0_fix.txt",
                "code_file": "out0_code.py",
                "scene_output_dir": "out0",
                "sim_success": "",
                "frames_ok": "",
                "accepted_by_user": "",
                "status": "generated_fix",
                "timestamp": "2026-02-05T00:00:01",
            }

        generator.generate_fix_shot = fake_generate_fix_shot

        record = SceneGenerator.process_scene(
            generator, {"keyword": "Red Light", "prompt": "red light violation"}
        )

        self.assertEqual(captured["next_shot_index"], 0)
        self.assertEqual(len(record["shot_artifacts"]), 1)
        self.assertEqual(record["shot_artifacts"][0]["shot_index"], 0)
        self.assertEqual(record["final_status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
