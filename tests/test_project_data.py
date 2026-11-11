from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.project_data import (
    entity_fingerprint, load_project, parse_project, snapshot_dependencies, validate_project,
)
from scripts.qc_check import extract_prompt_blocks, scan_document
from scripts.render_project import export_project, render_documents

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo" / "project.json"


class ProjectDataTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)

    def errors(self, data=None, previous=None):
        return "\n".join(validate_project(self.data if data is None else data, previous)[0])

    def test_valid_demo_and_unchanged_baseline(self):
        self.assertEqual(self.errors(previous=deepcopy(self.data)), "")

    def test_missing_beat_cannot_be_hidden_by_valid_prompt(self):
        beat = deepcopy(self.data["beats"][0])
        beat["id"] = "BEAT-UNUSED"
        self.data["beats"].append(beat)
        self.assertIn("剧情节拍未覆盖：BEAT-UNUSED", self.errors())

    def test_duplicate_global_identity_is_rejected(self):
        self.data["characters"].append(deepcopy(self.data["characters"][0]))
        self.assertIn("全局 ID 重复", self.errors())

    def test_unknown_asset_reference_is_rejected(self):
        self.data["shots"][0]["character_ids"].append("CHAR-MISSING")
        self.assertIn("未知或类型不符的引用 CHAR-MISSING", self.errors())

    def test_dialogue_omission_rewrite_and_repeat_are_detected(self):
        line = self.data["shots"][0]["segments"][0]["lines"][0]
        with self.subTest("rewrite"):
            altered = deepcopy(self.data)
            altered["shots"][0]["segments"][0]["lines"][0]["text"] = "换个门锁吧。"
            self.assertIn("未逐字继承", self.errors(altered))
        with self.subTest("omit"):
            altered = deepcopy(self.data)
            altered["shots"][0]["segments"][0]["lines"] = []
            self.assertIn("实际 0 次", self.errors(altered))
        with self.subTest("repeat"):
            self.data["shots"][0]["segments"][0]["lines"].append(deepcopy(line))
            self.assertIn("实际 2 次", self.errors())

    def test_punctuation_adjustment_preserves_spoken_words(self):
        self.data["shots"][0]["segments"][0]["lines"][0]["text"] = "门锁，换过了！"
        rebuilt = snapshot_dependencies(self.data)
        self.assertEqual(self.errors(rebuilt), "")

    def test_structured_time_must_start_at_zero(self):
        self.data["shots"][0]["segments"][0]["start"] = 0.5
        self.assertIn("起点应为 0", self.errors())

    def test_edit_without_revision_still_invalidates_dependents(self):
        self.data["characters"][0]["description"] += " 暗红长衫。"
        errors = self.errors()
        self.assertIn("SHOT-001: 依赖已失效", errors)
        self.assertIn("SHOT-002: 依赖已失效", errors)
        self.assertIn("上游已失效", errors)

    def test_only_relevant_shot_invalidates_on_prop_edit(self):
        self.data["props"][0]["description"] += " 匙柄刻有缺口。"
        errors = self.errors()
        self.assertIn("SHOT-002: 依赖已失效", errors)
        self.assertNotIn("SHOT-001:", errors)

    def test_missing_snapshot_is_not_an_escape_hatch(self):
        self.data["shots"][0]["depends_on"] = []
        self.assertIn("缺少依赖快照", self.errors())

    def test_downstream_capture_refuses_stale_upstream(self):
        self.data["characters"][0]["revision"] += 1
        with self.assertRaisesRegex(ValueError, "上游已失效"):
            snapshot_dependencies(self.data, [self.data["shots"][0]["dynamic_prompt_id"]])

    def test_baseline_catches_unversioned_edits_after_recapture(self):
        old = deepcopy(self.data)
        self.data["characters"][0]["description"] += " 暗红长衫。"
        rebuilt = snapshot_dependencies(self.data)
        self.assertIn("内容已修改但 revision 未增加", self.errors(rebuilt, old))

    def test_stable_id_survives_rename(self):
        old_id = self.data["characters"][0]["id"]
        self.data["characters"][0]["name"] = "新角色名"
        self.data["characters"][0]["revision"] += 1
        self.assertEqual(snapshot_dependencies(self.data)["characters"][0]["id"], old_id)

    def test_slot_bindings_cannot_be_added_only_in_text(self):
        self.data["prompts"][-1]["text"] += "\n@素材9 参考角色外观。禁止继承背景。"
        self.assertIn("正文素材位与 reference_bindings 不一致", self.errors())

    def test_template_outer_ratio_is_checked_against_its_scope(self):
        self.data["prompts"][0]["text"] = self.data["prompts"][0]["text"].replace("--ar 9:16", "--ar 16:9")
        self.assertIn("画幅须在末行唯一声明 --ar 9:16", self.errors())
        board = next(p for p in self.data["prompts"] if p["template"] == "T6B")
        board["text"] = board["text"].replace("--ar 16:9", "--ar 9:16")
        self.assertIn("画幅须在末行唯一声明 --ar 16:9", self.errors())

    def test_dependency_cycle_is_rejected(self):
        first, second = self.data["prompts"][:2]
        first["reference_bindings"].append({"slot": "@图片9", "asset_id": second["id"]})
        second["reference_bindings"].append({"slot": "@图片9", "asset_id": first["id"]})
        with self.assertRaisesRegex(ValueError, "依赖成环"):
            snapshot_dependencies(self.data)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_project(text)

    def test_fingerprint_ignores_only_dependency_metadata(self):
        original = deepcopy(self.data["shots"][0])
        changed = deepcopy(original)
        changed["depends_on"] = []
        self.assertEqual(entity_fingerprint(original), entity_fingerprint(changed))
        changed["duration"] += 1
        self.assertNotEqual(entity_fingerprint(original), entity_fingerprint(changed))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)

    def test_export_preserves_every_prompt_and_source_data(self):
        before = deepcopy(self.data)
        documents = render_documents(self.data)
        blocks = [block for text in documents.values() for block in extract_prompt_blocks(text)[0]]
        self.assertEqual(len(blocks), len(self.data["prompts"]))
        by_id = {block["prompt_id"]: block["text"] for block in blocks}
        self.assertEqual(by_id, {p["id"]: p["text"] for p in self.data["prompts"]})
        self.assertEqual(self.data, before)
        for name, text in documents.items():
            self.assertFalse([error for r in scan_document(text, name) for error in r["errors"]])

    def test_summary_has_fifteen_fields_and_preserves_review_state(self):
        text = render_documents(self.data)["project.md"]
        header = next(line for line in text.splitlines() if line.startswith("| 镜号 |"))
        self.assertEqual(len(header.split("|")[1:-1]), 15)
        self.assertIn("未审查", text)
        self.assertIn(self.data["shots"][0]["transitions"]["incoming"], text)

    def test_invalid_or_stale_data_does_not_create_output(self):
        self.data["characters"][0]["revision"] += 1
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "delivery"
            with self.assertRaises(ValueError):
                export_project(self.data, output)
            self.assertFalse(output.exists())

    def test_prompt_dialogue_omission_blocks_export(self):
        prompt = next(p for p in self.data["prompts"] if p["template"] == "T9")
        prompt["text"] = prompt["text"].replace("门锁换过了。", "")
        # Its own contents are changed; source dependency snapshots can still be fresh.
        with self.assertRaisesRegex(ValueError, "台词"):
            render_documents(self.data)

    def test_reexport_is_repeatable_and_manual_edits_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = export_project(self.data, temporary)
            before = {path.name: path.read_bytes() for path in paths}
            export_project(self.data, temporary)
            self.assertEqual(before, {path.name: path.read_bytes() for path in paths})
            paths[0].write_text("人工批注", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "手工修改"):
                export_project(self.data, temporary)
            self.assertEqual(paths[0].read_text(encoding="utf-8"), "人工批注")

    def test_unmanaged_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "project.md"
            target.write_text("已有文档", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "非托管"):
                export_project(self.data, temporary)
            self.assertEqual(target.read_text(encoding="utf-8"), "已有文档")


if __name__ == "__main__":
    unittest.main()
