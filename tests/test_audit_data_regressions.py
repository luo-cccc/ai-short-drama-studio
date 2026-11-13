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

    def test_visual_binding_owner_mismatch_and_multi_character_slot_swap_are_rejected(self):
        # 1. 绑定了角色资产 CHAR-WANQING，但参考声明写成场景或另一角色
        wrong_decl = deepcopy(self.data)
        p1 = next(item for item in wrong_decl["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        p1["text"] = p1["text"].replace(
            "@素材1 参考角色晚晴的外观，服饰，固有配色与画面风格。",
            "@素材1 参考场景旧院门的空间布局与结构。",
        )
        errors, _ = validate_project(snapshot_dependencies(wrong_decl))
        self.assertTrue(any("绑定了角色资产 CHAR-WANQING" in e for e in errors), errors)

        # 2. 双人同框时主体行互换 @素材1 与 @素材2 导致串脸 -> 报错拦截
        swapped = deepcopy(self.data)
        swapped["characters"].append({
            "id": "CHAR-LINZHOU",
            "revision": 1,
            "name": "林舟",
            "description": "青年东亚男性，方颌，剑眉，黑瞳，高束发，玄黑劲装，长靴。",
            "voice": "低沉男中音，匀速。",
        })
        swapped["beats"][0]["character_ids"].append("CHAR-LINZHOU")
        swapped["shots"][0]["character_ids"].append("CHAR-LINZHOU")
        p_swap = next(item for item in swapped["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        p_swap["asset_ids"].append("CHAR-LINZHOU")
        p_swap["reference_bindings"] = [
            {"slot": "@素材1", "asset_id": "CHAR-WANQING"},
            {"slot": "@素材2", "asset_id": "CHAR-LINZHOU"},
            {"slot": "@素材3", "asset_id": "SCENE-GATE"},
            {"slot": "@素材4", "asset_id": "PROMPT-BOARD-001"},
        ]
        p_swap["text"] = (
            "@素材1 参考角色晚晴的外观与五官骨相。禁止继承背景，叙事光影，整体调色，动作，表情。\n"
            "@素材2 参考角色林舟的外观与五官骨相。禁止继承背景，叙事光影，整体调色，动作，表情。\n"
            "@素材3 参考场景旧院门的空间布局。禁止继承画面风格，光影，色彩，构图，景别。\n"
            "@素材4 参考故事板九宫格关键帧画面的角色姿态。禁止继承画面风格，光影，色彩，构图，景别。\n"
            "生成一段单镜头5秒的悬疑短片，同步生成环境音，音效，配音与背景音乐，音画口型同步。画面纯净，无字幕。\n"
            "角色晚晴：参考@素材2，年轻东亚女性，窄脸，平直眉，深棕瞳孔，黑发低束，清瘦身形，灰蓝长衫，黑布鞋。\n"
            "角色林舟：参考@素材1，青年东亚男性，方颌，剑眉，黑瞳，高束发，玄黑劲装，长靴。\n"
            "场景旧院门：参考@素材3，青灰石阶与木门。\n"
            "整体情绪为警觉，从观察到开口。\n"
            "写实悬疑风格，冷白柔光。\n"
            "镜头1（0.0-5.0s）：平视中近景，晚晴以清亮女中音说：“门锁换过了。”\n"
            "新铜锁与指尖同时清楚入画，面部与低束发型连贯，衣袖贴合手臂。\n"
            "--ar 9:16"
        )
        swap_errors, _ = validate_project(snapshot_dependencies(swapped))
        self.assertTrue(any("角色晚晴的视觉参考槽 @素材2 指向了非本角色资产 CHAR-LINZHOU" in e for e in swap_errors), swap_errors)
        self.assertTrue(any("角色林舟的视觉参考槽 @素材1 指向了非本角色资产 CHAR-WANQING" in e for e in swap_errors), swap_errors)

        # 3. 跨分镜错绑另一镜头的九宫格故事板 -> 报错拦截
        cross_board = deepcopy(self.data)
        p2 = next(item for item in cross_board["prompts"] if item["id"] == "PROMPT-VIDEO-002")
        p2["reference_bindings"][-1]["asset_id"] = "PROMPT-BOARD-001"
        cross_errors, _ = validate_project(snapshot_dependencies(cross_board))
        self.assertTrue(any("属于另一分镜 SHOT-001" in e for e in cross_errors), cross_errors)

        # 4. 绑定静态空间图 PROMPT-SPACE-GATE（T5）却在声明中写为角色参考，或道具行错引角色槽位 -> 报错拦截
        wrong_static = deepcopy(self.data)
        p2_static = next(item for item in wrong_static["prompts"] if item["id"] == "PROMPT-VIDEO-002")
        p2_static["reference_bindings"][1]["asset_id"] = "PROMPT-SPACE-GATE"
        p2_static["text"] = p2_static["text"].replace(
            "@素材2 参考场景旧院门的空间布局与关键定锚物位置。禁止继承画面风格，光影，色彩，构图，景别。",
            "@素材2 参考角色晚晴的五官与服饰。禁止继承背景。",
        ).replace(
            "道具铜钥匙：参考@素材3",
            "道具铜钥匙：参考@素材1",
        )
        static_errors, _ = validate_project(snapshot_dependencies(wrong_static))
        self.assertTrue(any("绑定了场景参考图 PROMPT-SPACE-GATE（T5），但参考声明主语不是场景" in e for e in static_errors), static_errors)
        self.assertTrue(any("道具铜钥匙的视觉参考槽 @素材1 指向了非本道具资产 CHAR-WANQING" in e for e in static_errors), static_errors)


if __name__ == "__main__":
    unittest.main()
