"""Regression coverage for safe data writes, shared identities, and dialogue cues."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.project_data import (
    _write_json, load_project, main, snapshot_dependencies, sync_shared_assets,
    validate_project, validate_shared_assets,
)


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo" / "project.json"
SOURCE = ROOT / "examples" / "demo" / "preproduction.md"


def run_cli(script, *args):
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts" / script), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )


class DataWriteRegressionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)

    def test_real_cli_encoding_failure_preserves_original_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = directory / "project.json"
            original = DEMO.read_bytes()
            project.write_bytes(original)
            character = deepcopy(self.data["characters"][0])
            character.update(description="\ud800", revision=character["revision"] + 1)
            shared = directory / "shared.json"
            shared.write_text(json.dumps({"characters": [character]}, ensure_ascii=True), encoding="utf-8")

            result = run_cli("project_data.py", "sync-assets", project, "--from", shared, "--in-place")

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("ERROR", result.stderr)
            self.assertEqual(project.read_bytes(), original)
            self.assertEqual(set(directory.iterdir()), {project, shared})

    def test_replace_failure_preserves_original_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = directory / "project.json"
            original = DEMO.read_bytes()
            project.write_bytes(original)
            shared = directory / "shared.json"
            shared.write_text("{}", encoding="utf-8")
            with patch("scripts.project_data.os.replace", side_effect=PermissionError("replace denied")) as replace:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    status = main(["sync-assets", str(project), "--from", str(shared), "--in-place"])

            self.assertEqual(status, 1)
            replace.assert_called_once()
            staged, target = map(Path, replace.call_args.args)
            self.assertEqual(staged.parent, directory)
            self.assertEqual(target, project)
            self.assertEqual(project.read_bytes(), original)
            self.assertEqual(set(directory.iterdir()), {project, shared})

    def test_temporary_write_failure_preserves_original_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = directory / "project.json"
            project.write_bytes(b"original bytes")
            with patch("scripts.project_data.os.fsync", side_effect=OSError("disk write failed")):
                with self.assertRaisesRegex(OSError, "disk write failed"):
                    _write_json({"updated": True}, project, in_place=True)
            self.assertEqual(project.read_bytes(), b"original bytes")
            self.assertEqual(list(directory.iterdir()), [project])

    def test_successful_in_place_write_replaces_complete_utf8_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = directory / "project.json"
            project.write_bytes(b"old")
            _write_json({"title": "新项目"}, project, in_place=True)
            self.assertEqual(load_project(project), {"title": "新项目"})
            self.assertTrue(project.read_bytes().endswith(b"\n"))
            self.assertEqual(list(directory.iterdir()), [project])

    def test_real_cli_output_refuses_to_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            shared = directory / "shared.json"
            shared.write_text("{}", encoding="utf-8")
            output = directory / "existing.json"
            output.write_bytes(b"keep this file")
            result = run_cli("project_data.py", "sync-assets", DEMO, "--from", shared, "--output", output)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(output.read_bytes(), b"keep this file")

    def test_real_cli_unknown_source_speaker_returns_json_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project.json"
            self.data["dialogues"][0]["speaker_id"] = "CHAR-MISSING"
            project.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

            result = run_cli("qc_check.py", project, "--source", SOURCE, "--format", "json")

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            diagnostics = json.loads(result.stdout)
            self.assertFalse(diagnostics["ok"])
            errors = [error for item in diagnostics["results"] for error in item["errors"]]
            self.assertTrue(any("CHAR-MISSING" in error and "未知" in error for error in errors), errors)
            self.assertNotIn("Traceback", result.stderr)


class SharedIdentityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)

    def test_duplicate_existing_and_new_character_and_global_prompt_ids_are_rejected(self):
        for collection in ("characters", "prompts"):
            if collection == "characters":
                original = self.data[collection][0]
                field, new_id = "description", "CHAR-SHARED-NEW"
            else:
                original = next(prompt for prompt in self.data[collection] if prompt["shot_id"] is None)
                field, new_id = "text", "PROMPT-SHARED-NEW"
            for include_new in (False, True):
                with self.subTest(collection=collection, include_new=include_new):
                    target = deepcopy(original)
                    if include_new:
                        target["id"] = new_id
                    shadowed = deepcopy(target)
                    shadowed[field] += " 不应被静默忽略的冲突内容。"
                    shared = {collection: [shadowed, target]}
                    before = deepcopy(self.data)

                    errors = validate_shared_assets(self.data, shared)

                    self.assertTrue(any("ID 重复" in error and target["id"] in error for error in errors), errors)
                    with self.assertRaisesRegex(ValueError, "ID 重复"):
                        sync_shared_assets(self.data, shared, include_new=include_new)
                    self.assertEqual(self.data, before)

    def test_unique_new_character_and_global_prompt_are_added_once(self):
        character = dict(self.data["characters"][0], id="CHAR-SHARED-NEW")
        prompt = dict(next(p for p in self.data["prompts"] if p["shot_id"] is None), id="PROMPT-SHARED-NEW")
        shared = {"characters": [character], "prompts": [prompt]}
        synced = sync_shared_assets(self.data, shared, include_new=True)
        synced_again = sync_shared_assets(synced, shared, include_new=True)
        self.assertEqual(sum(item["id"] == character["id"] for item in synced_again["characters"]), 1)
        self.assertEqual(sum(item["id"] == prompt["id"] for item in synced_again["prompts"]), 1)


class DialogueCueRegressionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)
        for shot in self.data["shots"]:
            for segment in shot["segments"]:
                for delivery in segment["lines"]:
                    delivery.pop("start", None)
                    delivery.pop("end", None)

    @property
    def first_delivery(self):
        return self.data["shots"][0]["segments"][0]["lines"][0]

    def errors(self):
        return validate_project(snapshot_dependencies(self.data))[0]

    def add_first_shot_dialogue(self):
        line = dict(self.data["dialogues"][0], id="LINE-CUE-EXTRA", text="再看一眼。")
        self.data["dialogues"].insert(1, line)
        delivery = {"dialogue_id": line["id"], "text": line["text"]}
        self.data["shots"][0]["segments"][0]["lines"].append(delivery)
        return delivery

    def split_first_shot(self):
        shot = self.data["shots"][0]
        shot["segments"][0]["end"] = 2.5
        shot["segments"].append({
            "index": 2, "start": 2.5, "end": 5.0,
            "description": "切到门锁细节，声音保持连续。", "lines": [],
        })

    def test_legacy_dialogues_without_cues_remain_valid_and_unchanged(self):
        data = snapshot_dependencies(self.data)
        before = deepcopy(data)
        self.assertEqual(validate_project(data)[0], [])
        self.assertEqual(data, before)

    def test_partial_cue_is_rejected(self):
        for field in ("start", "end"):
            with self.subTest(field=field):
                self.first_delivery.pop("start", None)
                self.first_delivery.pop("end", None)
                self.first_delivery[field] = 2.0
                self.assertTrue(any("成对" in error for error in self.errors()))

    def test_reversed_or_empty_cue_is_rejected(self):
        for cue_end in (1.5, 2.0):
            with self.subTest(end=cue_end):
                self.first_delivery.update(start=2.0, end=cue_end)
                self.assertTrue(any("end 必须大于 start" in error for error in self.errors()))

    def test_start_at_segment_end_is_rejected(self):
        self.split_first_shot()
        self.first_delivery.update(start=2.5, end=3.0)
        self.assertTrue(any("start 必须落在所属镜头" in error for error in self.errors()))

    def test_start_before_owning_segment_is_rejected(self):
        self.split_first_shot()
        shot = self.data["shots"][0]
        delivery = shot["segments"][0]["lines"].pop()
        delivery.update(start=2.0, end=3.0)
        shot["segments"][1]["lines"].append(delivery)
        self.assertTrue(any("start 必须落在所属镜头" in error for error in self.errors()))

    def test_end_after_shot_duration_is_rejected(self):
        self.first_delivery.update(start=4.0, end=5.1)
        self.assertTrue(any("end 不得超过分镜 duration" in error for error in self.errors()))

    def test_cue_start_cannot_go_backwards_in_execution_order(self):
        extra = self.add_first_shot_dialogue()
        self.first_delivery.update(start=3.0, end=3.5)
        extra.update(start=2.0, end=2.5)
        self.assertTrue(any("按执行顺序不得回退" in error for error in self.errors()))

    def test_cue_may_continue_across_a_physical_cut(self):
        self.split_first_shot()
        self.first_delivery.update(start=2.0, end=3.0)
        self.assertEqual(self.errors(), [])

    def test_unmarked_dialogue_does_not_require_an_invented_cue(self):
        self.first_delivery.update(start=2.0, end=3.0)
        self.add_first_shot_dialogue()
        self.assertEqual(self.errors(), [])

    def test_local_cue_clock_restarts_for_the_next_shot(self):
        self.first_delivery.update(start=4.0, end=4.5)
        second = self.data["shots"][1]["segments"][0]["lines"][0]
        second.update(start=0.0, end=0.5)
        self.assertEqual(self.errors(), [])


if __name__ == "__main__":
    unittest.main()
