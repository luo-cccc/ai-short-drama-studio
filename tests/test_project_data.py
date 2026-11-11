from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.project_data import (
    entity_fingerprint, find_stale_entities, load_project, main as project_data_main,
    parse_project, parse_source_script, snapshot_dependencies, sync_shared_assets,
    validate_project, validate_shared_assets, validate_source_script,
)
from scripts.qc_check import extract_prompt_blocks, scan_document
from scripts.render_project import export_project, render_documents

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo" / "project.json"
PREPRODUCTION = Path(__file__).resolve().parents[1] / "examples" / "demo" / "preproduction.md"


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

    def test_duplicate_shot_design_emits_warning_while_demo_is_clean(self):
        errors, warnings = validate_project(self.data)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        copied = deepcopy(self.data)
        copied["shots"][1]["design"] = deepcopy(copied["shots"][0]["design"])
        rebuilt = snapshot_dependencies(copied)
        errors, warnings = validate_project(rebuilt)
        self.assertEqual(errors, [])
        self.assertTrue(any("SHOT-002: 八岗位设计决策与 SHOT-001 完全相同" in w for w in warnings), warnings)

    def test_source_script_validation_accepts_demo_preproduction_and_catches_drift(self):
        source_text = PREPRODUCTION.read_text(encoding="utf-8")
        errors, _ = validate_project(self.data, source_text=source_text)
        self.assertEqual(errors, [])

        with self.subTest("dialogue_text_drift"):
            drifted_source = source_text.replace("门锁换过了。", "门锁怎么换了？")
            self.assertTrue(any("台词内容" in e for e in validate_source_script(self.data, drifted_source)))

        with self.subTest("extra_dialogue_line"):
            extra_source = source_text + "\nE01-S01-D03：晚晴：里面有人。\n"
            self.assertTrue(any("台词数量" in e for e in validate_source_script(self.data, extra_source)))

        with self.subTest("broken_beat_shot_mapping"):
            bad_mapping = source_text.replace("BEAT-LOCK→SHOT-001", "BEAT-LOCK→SHOT-002")
            self.assertTrue(any("BEAT-LOCK→SHOT-002" in e for e in validate_source_script(self.data, bad_mapping)))

        with self.subTest("source_ref_validation"):
            anchored = deepcopy(self.data)
            anchored["beats"][0]["source_ref"] = "E01-S01-A01"
            anchored["dialogues"][0]["source_ref"] = "E01-S01-D01"
            self.assertEqual(validate_source_script(anchored, source_text), [])
            anchored["dialogues"][0]["source_ref"] = "E01-S01-D99"
            self.assertTrue(any("E01-S01-D99" in e for e in validate_source_script(anchored, source_text)))

    def test_standard_scene_script_format_is_parsed_and_verified(self):
        standard_script = "\n".join([
            "01-01  昏  阴  外  旧院门",
            "",
            "出场人物：晚晴",
            "道具：铜钥匙",
            "",
            "△ 晚晴停在石阶上，面向入口右侧门扇，目光从门闩移向新锁。",
            "晚晴（压低声音）：门锁换过了。",
            "△ 她看向门框缝隙，抽出铜钥匙托在掌心。",
            "晚晴：钥匙还在这里。",
            "【音效：指尖碰到锁环，铜件轻响。】",
        ])
        parsed = parse_source_script(standard_script)
        self.assertEqual(len(parsed["actions"]), 2)
        self.assertEqual(len(parsed["dialogues"]), 2)
        self.assertEqual(validate_source_script(self.data, standard_script), [])

    def test_shared_assets_validation_and_sync_workflow(self):
        shared = {
            "characters": deepcopy(self.data["characters"]),
            "scenes": deepcopy(self.data["scenes"]),
            "props": deepcopy(self.data["props"]),
            "prompts": [deepcopy(self.data["prompts"][0])],
        }
        self.assertEqual(validate_shared_assets(self.data, shared), [])

        shared["characters"][0]["description"] += " 袖口绣有银线。"
        shared["characters"][0]["revision"] += 1
        drift_errors = validate_project(self.data, shared_assets=shared)[0]
        self.assertTrue(any("CHAR-WANQING: 与共享资产库不一致" in e for e in drift_errors), drift_errors)

        synced = sync_shared_assets(self.data, shared)
        self.assertEqual(validate_shared_assets(synced, shared), [])
        stale_ids = find_stale_entities(synced)
        self.assertIn("SHOT-001", stale_ids)
        self.assertIn("PROMPT-VIDEO-001", stale_ids)
        recaptured = snapshot_dependencies(synced, stale_ids)
        self.assertEqual(validate_project(recaptured, shared_assets=shared)[0], [])

    def test_cli_capture_all_stale_inplace_sync_and_extract(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            draft_path = temp_dir / "draft.json"
            draft = deepcopy(self.data)
            for item in draft["shots"] + draft["prompts"]:
                item["depends_on"] = []
            draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")

            captured_path = temp_dir / "captured.json"
            with redirect_stdout(io.StringIO()):
                status = project_data_main(["capture", str(draft_path), "--all", "--output", str(captured_path)])
            self.assertEqual(status, 0)
            self.assertEqual(validate_project(load_project(captured_path))[0], [])

            shared_path = temp_dir / "shared.json"
            shared = {"props": deepcopy(self.data["props"])}
            shared["props"][0]["description"] += " 边缘微亮。"
            shared["props"][0]["revision"] += 1
            shared_path.write_text(json.dumps(shared, ensure_ascii=False), encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                status = project_data_main(["sync-assets", str(captured_path), "--from", str(shared_path), "--in-place"])
            self.assertEqual(status, 0)
            self.assertEqual(find_stale_entities(load_project(captured_path)), ["PROMPT-BOARD-002", "PROMPT-VIDEO-002", "SHOT-002"])

            with redirect_stdout(io.StringIO()):
                status = project_data_main(["capture", str(captured_path), "--stale", "--in-place"])
            self.assertEqual(status, 0)
            self.assertEqual(validate_project(load_project(captured_path), shared_assets=shared)[0], [])

            extracted_out = io.StringIO()
            with redirect_stdout(extracted_out):
                status = project_data_main(["extract-script", str(PREPRODUCTION)])
            self.assertEqual(status, 0)
            extracted = json.loads(extracted_out.getvalue())
            self.assertEqual(len(extracted["dialogues"]), 2)

            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                project_data_main(["capture", str(captured_path), "--in-place"])
            self.assertEqual(ctx.exception.code, 2)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)

    def single_shot_data(self):
        data = deepcopy(self.data)
        data["shots"] = data["shots"][:1]
        shot_ids = {shot["id"] for shot in data["shots"]}
        beat_ids = {beat_id for shot in data["shots"] for beat_id in shot["beat_ids"]}
        data["beats"] = [beat for beat in data["beats"] if beat["id"] in beat_ids]
        data["dialogues"] = [line for line in data["dialogues"] if line["beat_id"] in beat_ids]
        data["prompts"] = [prompt for prompt in data["prompts"]
                           if prompt["shot_id"] is None or prompt["shot_id"] in shot_ids]
        return snapshot_dependencies(data)

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

    def test_source_dialogue_order_survives_return_to_an_earlier_beat(self):
        silent = deepcopy(self.data["beats"][0])
        silent.update(id="BEAT-SILENT", summary="晚晴停住，院外风声延续。")
        self.data["beats"].insert(1, silent)
        self.data["shots"][0]["beat_ids"].append(silent["id"])
        returned = deepcopy(self.data["dialogues"][0])
        returned.update(id="LINE-RETURN", text="再看一眼门锁。")
        self.data["dialogues"].append(returned)
        last_shot = self.data["shots"][-1]
        last_shot["beat_ids"].append(returned["beat_id"])
        last_shot["segments"][-1]["lines"].append({
            "dialogue_id": returned["id"], "text": returned["text"],
        })
        prompt = next(p for p in self.data["prompts"] if p["id"] == last_shot["dynamic_prompt_id"])
        previous_quote = "“" + self.data["dialogues"][1]["text"] + "”"
        prompt["text"] = prompt["text"].replace(
            previous_quote, previous_quote + "她回看门锁：“" + returned["text"] + "”")
        data = snapshot_dependencies(self.data)
        text = render_documents(data)["project.md"]
        source = text.split("## 剧本节拍与原始台词", 1)[1].split("## 静态资产总库", 1)[0]
        dialogue_rows = [line for line in source.splitlines()
                         if any(item["id"] in line for item in data["dialogues"])]
        self.assertEqual(len(dialogue_rows), len(data["dialogues"]))
        self.assertEqual([next(item["id"] for item in data["dialogues"] if item["id"] in row)
                          for row in dialogue_rows], [item["id"] for item in data["dialogues"]])
        for item, row in zip(data["dialogues"], dialogue_rows):
            self.assertIn(item["beat_id"], row)
            self.assertIn(item["text"], row)
            self.assertEqual(source.count(item["text"]), 1)
        for beat in data["beats"]:
            self.assertIn(beat["id"], source)
            self.assertEqual(source.count(beat["summary"]), 1)

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

    def test_obsolete_files_remain_reported_until_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            export_project(self.data, output)
            stale_name = self.data["shots"][1]["id"] + "_分镜.md"
            stale = output / stale_name
            original = stale.read_bytes()
            reduced = self.single_shot_data()
            for _ in range(2):
                _, obsolete = export_project(reduced, output)
                self.assertEqual(obsolete, [stale_name])
                manifest = load_project(output / ".drama-export.json")
                self.assertEqual(manifest["obsolete_files"], [stale_name])
                self.assertEqual(stale.read_bytes(), original)
            stale.unlink()
            _, obsolete = export_project(reduced, output)
            self.assertEqual(obsolete, [])
            manifest = load_project(output / ".drama-export.json")
            self.assertEqual(manifest["obsolete_files"], [])
            self.assertNotIn(stale_name, manifest["obsolete_file_fingerprints"])

    def test_unchanged_obsolete_file_can_be_restored_to_managed_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            export_project(self.data, output)
            export_project(self.single_shot_data(), output)
            restored = deepcopy(self.data)
            restored["shots"][1]["title"] += " · 修订"
            restored["shots"][1]["revision"] += 1
            restored = snapshot_dependencies(restored)
            _, obsolete = export_project(restored, output)
            self.assertEqual(obsolete, [])
            manifest = load_project(output / ".drama-export.json")
            restored_name = self.data["shots"][1]["id"] + "_分镜.md"
            self.assertIn(restored_name, manifest["files"])
            self.assertNotIn(restored_name, manifest["obsolete_file_fingerprints"])
            self.assertEqual((output / restored_name).read_text(encoding="utf-8"),
                             render_documents(restored)[restored_name])

    def test_manually_edited_obsolete_file_blocks_restore_before_any_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            export_project(self.data, output)
            reduced = self.single_shot_data()
            export_project(reduced, output)
            stale = output / (self.data["shots"][1]["id"] + "_分镜.md")
            stale.write_text("过期镜头的人工批注", encoding="utf-8")
            export_project(reduced, output)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaisesRegex(ValueError, "手工修改"):
                export_project(self.data, output)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_legacy_obsolete_record_persists_but_does_not_prove_safe_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            export_project(self.data, output)
            reduced = self.single_shot_data()
            export_project(reduced, output)
            manifest_path = output / ".drama-export.json"
            manifest = load_project(manifest_path)
            manifest.pop("obsolete_file_fingerprints", None)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            stale_name = self.data["shots"][1]["id"] + "_分镜.md"
            _, obsolete = export_project(reduced, output)
            self.assertEqual(obsolete, [stale_name])
            before = (output / stale_name).read_bytes()
            with self.assertRaisesRegex(ValueError, "非托管"):
                export_project(self.data, output)
            self.assertEqual((output / stale_name).read_bytes(), before)

    def test_replacement_after_obsolete_cleanup_is_unmanaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            export_project(self.data, output)
            reduced = self.single_shot_data()
            export_project(reduced, output)
            stale = output / (self.data["shots"][1]["id"] + "_分镜.md")
            stale.unlink()
            export_project(reduced, output)
            stale.write_text("同名新文档", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "非托管"):
                export_project(self.data, output)
            self.assertEqual(stale.read_text(encoding="utf-8"), "同名新文档")


if __name__ == "__main__":
    unittest.main()
