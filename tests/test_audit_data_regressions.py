"""Regressions discovered by a cross-module data and source audit."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest

from scripts.project_data import (
    entity_index, load_project, main, parse_project, parse_source_script,
    snapshot_dependencies, sync_shared_assets, validate_project,
    validate_shared_assets, validate_source_script,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "\n".join((
    "E01-S01-A01：△ 门锁换过了。",
    "E01-S01-D01：晚晴：门锁换过了。",
    "E01-S01-D02：晚晴：钥匙还在这里。",
))


class AuditDataRegressionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(ROOT / "examples/demo/project.json")

    def test_numeric_overflow_is_rejected_during_json_parsing(self):
        for value in ("1e999", "-1e999", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "非有限"):
                parse_project('{"value":' + value + '}')
        self.assertEqual({"value": 1.25}, parse_project('{"value":1.25}'))

    def test_capture_refuses_duplicate_identity_instead_of_choosing_last(self):
        self.data["characters"].append(deepcopy(self.data["characters"][0]))
        before = deepcopy(self.data)
        with self.assertRaisesRegex(ValueError, "全局 ID 重复"):
            snapshot_dependencies(self.data)
        self.assertEqual(before, self.data)
        with self.assertRaisesRegex(ValueError, "全局 ID 重复"):
            entity_index(self.data)

    def test_shared_sync_refuses_duplicate_destination_identity(self):
        self.data["characters"].append(deepcopy(self.data["characters"][0]))
        with self.assertRaisesRegex(ValueError, "全局 ID 重复"):
            sync_shared_assets(self.data, {})

    def test_baseline_duplicate_identity_is_reported_without_crash(self):
        previous = deepcopy(self.data)
        previous["characters"].append(deepcopy(previous["characters"][0]))
        errors, _ = validate_project(self.data, previous=previous)
        self.assertTrue(any("基线数据非法" in error and "ID 重复" in error for error in errors), errors)

    def test_global_shared_dynamic_prompt_is_rejected_before_sync(self):
        prompt = deepcopy(self.data["prompts"][-1])
        prompt.update(id="PROMPT-INVALID-GLOBAL", shot_id=None)
        shared = {"prompts": [prompt]}
        before = deepcopy(self.data)
        self.assertTrue(any("全局共享提示词必须使用静态模板" in error
                            for error in validate_shared_assets(self.data, shared)))
        with self.assertRaisesRegex(ValueError, "静态模板"):
            sync_shared_assets(self.data, shared, include_new=True)
        self.assertEqual(before, self.data)

    def test_named_offscreen_dialogue_keeps_character_identity(self):
        source = "晚晴（画外音）：门锁换过了。\n晚晴：钥匙还在这里。"
        parsed = parse_source_script(source, known_speakers={"晚晴"})
        self.assertEqual(("dialogue", "晚晴"), (parsed["dialogues"][0]["kind"], parsed["dialogues"][0]["speaker"]))
        self.assertEqual([], validate_source_script(self.data, source))

    def test_named_narration_and_internal_voice_keep_their_speaker(self):
        parsed = parse_source_script("晚晴（NAR）：那时我还不知道。\n晚晴（OS）：先等等。\n旁白：夜深了。")
        self.assertEqual([("narration", "晚晴"), ("os", "晚晴"), ("narration", None)],
                         [(item["kind"], item["speaker"]) for item in parsed["dialogues"]])

    def test_duplicate_source_anchor_is_an_error(self):
        source = "E01-S01-A01：△ 看向门锁。\n" + SOURCE
        errors = validate_source_script(self.data, source)
        self.assertTrue(any("源剧本定位 ID 重复" in error for error in errors), errors)

    def test_extract_refuses_duplicate_anchor_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            output = Path(directory) / "extracted.json"
            source.write_text("E01-S01-A01：△ 看向门锁。\n" + SOURCE, encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = main(["extract-script", str(source), "--output", str(output)])
            self.assertEqual(1, status)
            self.assertFalse(output.exists())

    def test_same_text_action_cannot_be_claimed_as_dialogue_source(self):
        self.data["dialogues"][0]["source_ref"] = "E01-S01-A01"
        errors = validate_source_script(self.data, SOURCE)
        self.assertTrue(any("必须指向台词" in error for error in errors), errors)

    def test_same_text_action_mapping_cannot_be_claimed_as_dialogue(self):
        errors = validate_source_script(self.data, SOURCE + "\n| A01→LINE-LOCK |")
        self.assertTrue(any("必须指向台词" in error for error in errors), errors)

    def test_same_words_from_another_speaker_cannot_satisfy_source_ref(self):
        character = dict(self.data["characters"][0], id="CHAR-LINZHOU", name="林舟")
        self.data["characters"].append(character)
        self.data["dialogues"][1].update(speaker_id="CHAR-LINZHOU", text="门锁换过了。")
        self.data["dialogues"][0]["source_ref"] = "E01-S01-D02"
        source = "E01-S01-D01：晚晴：门锁换过了。\nE01-S01-D02：林舟：门锁换过了。"
        errors = validate_source_script(self.data, source)
        self.assertTrue(any("source_ref" in error and "说话角色" in error for error in errors), errors)

    def test_voice_ids_in_source_handoff_are_checked(self):
        errors = validate_source_script(self.data, SOURCE + "\n本场声音资产为VOICE-MISSING。")
        self.assertTrue(any("VOICE-MISSING" in error for error in errors), errors)

    def test_chinese_adjacent_source_mapping_is_not_silently_ignored(self):
        errors = validate_source_script(self.data, SOURCE + "\n映射BEAT-LOCK→SHOT-002。")
        self.assertTrue(any("BEAT-LOCK→SHOT-002" in error for error in errors), errors)

    def test_audio_identity_declaration_cannot_bind_character_image(self):
        prompt = next(item for item in self.data["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        prompt["text"] = prompt["text"].replace(
            "@素材1 参考角色晚晴的外观，服饰，固有配色与画面风格。",
            "@素材1 参考角色晚晴的声音身份与音色。")
        errors, _ = validate_project(snapshot_dependencies(self.data))
        self.assertTrue(any("必须绑定 VOICE-" in error for error in errors), errors)

    def test_negative_audio_exclusion_is_still_a_visual_reference(self):
        prompt = next(item for item in self.data["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        prompt["text"] = prompt["text"].replace(
            "禁止继承背景，叙事光影，整体调色，动作，表情。",
            "禁止继承背景，叙事光影，整体调色，动作，表情，声音身份与音色。", 1)
        self.assertEqual([], validate_project(snapshot_dependencies(self.data))[0])

    def test_short_fence_does_not_close_long_ignored_source_block(self):
        source = "\n".join(("````python", "```", "假角色：不属于源剧本。", "````", SOURCE))
        self.assertEqual([], validate_source_script(self.data, source))

    def test_negative_voice_mention_does_not_satisfy_owner_declaration(self):
        data = load_project(ROOT / "examples/voice-reference/project.json")
        voice = data["voices"][0]
        voice.update(status="ready", audition="approved")
        voice["master"] = {"path": "master.wav", "sha256": "0" * 64,
                           "duration": 1.0, "transcript": "试听声音。"}
        voice["references"] = [{"id": "video-a", "model_id": "test-video-a", "path": "ref.wav",
                                "sha256": "0" * 64, "duration": 1.0,
                                "source_start": 0.0, "source_end": 1.0, "transcript": "试听声音。"}]
        prompt = next(item for item in data["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        prompt["asset_ids"].append(voice["id"])
        prompt["reference_bindings"].append({"slot": "@素材4", "asset_id": voice["id"], "audio_reference_id": "video-a"})
        prompt["audio_reference_profile"] = {"model_id": "test-video-a", "supports_voice_reference": True,
                                            "max_files": 1, "max_file_duration": 1.0, "max_total_duration": 1.0,
                                            "formats": ["wav"], "source": "测试配置"}
        prompt["text"] = "@素材4 参考角色林舟的声音身份。禁止继承晚晴声音。\n" + prompt["text"]
        errors, _ = validate_project(snapshot_dependencies(data))
        self.assertTrue(any("未明确所属角色" in error for error in errors), errors)

        voice.update(character_id=None, name="沉稳叙述者")
        data["dialogues"][0].update(speaker_id=None, kind="narration")
        prompt["text"] = prompt["text"].replace(
            "@素材4 参考角色林舟的声音身份。禁止继承晚晴声音。",
            "@素材4 参考旁白的声音身份与音色。禁止继承样片内容。")
        self.assertEqual([], validate_project(snapshot_dependencies(data))[0])


if __name__ == "__main__":
    unittest.main()
