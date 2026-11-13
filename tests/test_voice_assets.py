"""Voice identity references, model budgets, revisions and real local media."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
import wave

from scripts.project_data import (
    find_stale_entities, load_project, snapshot_dependencies, sync_shared_assets,
    validate_project, validate_shape, validate_shared_assets, validate_voice_media,
)


ROOT = Path(__file__).resolve().parents[1]


def reference_project():
    data = load_project(ROOT / "examples/demo/project.json")
    data["schema_version"] = "1.1"
    data["voices"] = [{
        "id": "VOICE-WANQING", "revision": 1, "name": "晚晴常态声音",
        "character_id": "CHAR-WANQING", "description": "清亮偏实声，字头清楚。",
        "language": "zh-CN", "source": "测试夹具，不代表真实人物音频",
        "status": "ready", "audition": "approved", "notes": "",
        "master": {"path": "master.wav", "sha256": "0" * 64,
                   "duration": 2.0, "transcript": "今天风很轻，明天再出发。"},
        "references": [{"id": "video-a", "model_id": "test-video-a",
                        "path": "reference.wav", "sha256": "0" * 64,
                        "duration": 1.0, "source_start": 0.0, "source_end": 1.0,
                        "transcript": "今天风很轻。"}],
    }]
    prompt = next(p for p in data["prompts"] if p["id"] == "PROMPT-VIDEO-001")
    prompt["asset_ids"].append("VOICE-WANQING")
    prompt["reference_bindings"].append({"slot": "@素材4", "asset_id": "VOICE-WANQING",
                                         "audio_reference_id": "video-a"})
    prompt["text"] = "@素材4 参考角色晚晴的声音身份、音色与咬字。禁止继承样片台词、情绪和背景声。\n" + prompt["text"]
    prompt["audio_reference_profile"] = {
        "model_id": "test-video-a", "supports_voice_reference": True,
        "max_files": 1, "max_file_duration": 1.0, "max_total_duration": 1.0,
        "formats": ["wav"], "source": "测试上限，不代表平台规格",
    }
    return snapshot_dependencies(data)


class VoiceAssetTests(unittest.TestCase):
    def setUp(self):
        self.data = reference_project()
        self.voice = self.data["voices"][0]
        self.prompt = next(p for p in self.data["prompts"] if p["id"] == "PROMPT-VIDEO-001")

    def errors(self):
        data = snapshot_dependencies(self.data)
        return "\n".join(validate_project(data)[0])

    def test_ready_model_reference_and_legacy_demo_are_valid(self):
        self.assertEqual(([], []), validate_project(self.data))
        self.assertEqual(([], []), validate_project(load_project(ROOT / "examples/demo/project.json")))

    def test_planning_example_reconciles_with_its_source_without_audio(self):
        directory = ROOT / "examples/voice-reference"
        data = load_project(directory / "project.json")
        errors, warnings = validate_project(data, source_text=(directory / "preproduction.md").read_text(encoding="utf-8"))
        self.assertFalse(errors, errors)
        self.assertTrue(any("待制作" in item for item in warnings))
        voice = data["voices"][0]
        self.assertTrue(voice["audition_text"])
        self.assertIsNone(voice["master"])
        self.assertFalse(voice["references"])
        self.assertFalse(any(binding["asset_id"].startswith("VOICE-")
                             for prompt in data["prompts"] for binding in prompt["reference_bindings"]))

    def test_voice_fields_require_schema_1_1(self):
        self.data["schema_version"] = "1.0"
        self.assertTrue(any("1.1" in error for error in validate_shape(self.data)))

    def test_bad_voice_shape_cannot_reach_relationship_checks(self):
        self.voice["master"]["sha256"] = "not-a-fingerprint"
        errors, _ = validate_project(self.data)
        self.assertTrue(any("sha256" in error for error in errors))

    def test_planned_asset_is_valid_without_files_or_upload_slots(self):
        data = load_project(ROOT / "examples/demo/project.json")
        data["schema_version"] = "1.1"
        planned = deepcopy(self.voice)
        planned.update(status="planned", audition="unreviewed", master=None, references=[])
        data["voices"] = [planned]
        errors, warnings = validate_project(data)
        self.assertFalse(errors)
        self.assertTrue(any("待制作" in warning for warning in warnings))

    def test_planned_asset_cannot_claim_files_or_bindings(self):
        self.voice["status"] = "planned"
        self.assertIn("planned", self.errors())
        self.voice.update(master=None, references=[], audition="unreviewed")
        self.assertIn("尚未 ready", self.errors())

    def test_ready_requires_master_and_reference_id(self):
        self.voice["master"] = None
        self.assertIn("必须登记母版", self.errors())
        self.voice["master"] = reference_project()["voices"][0]["master"]
        self.prompt["reference_bindings"][-1].pop("audio_reference_id")
        self.assertIn("audio_reference_id", self.errors())

    def test_role_and_reference_declaration_must_match(self):
        self.voice["character_id"] = "CHAR-MISSING"
        self.assertIn("未知角色", self.errors())
        self.voice["character_id"] = "CHAR-WANQING"
        self.prompt["text"] = self.prompt["text"].replace("参考角色晚晴的声音", "参考角色林舟的声音")
        self.assertIn("未明确所属角色", self.errors())

    def test_narrator_reference_requires_narration_in_its_shot(self):
        self.voice.update(character_id=None, name="旁白声音")
        self.assertIn("旁白声音未对应", self.errors())

    def test_audio_binding_requires_asset_and_target_profile(self):
        self.prompt["asset_ids"].remove(self.voice["id"])
        self.assertIn("未列入 asset_ids", self.errors())
        self.prompt["asset_ids"].append(self.voice["id"])
        self.prompt.pop("audio_reference_profile")
        self.assertIn("audio_reference_profile", self.errors())

    def test_static_references_cannot_include_voices(self):
        static = self.data["prompts"][0]
        static["asset_ids"].append(self.voice["id"])
        self.assertIn("静态提示词不能使用声音", self.errors())

    def test_role_body_cannot_swap_two_correctly_declared_voice_slots(self):
        character = deepcopy(self.data["characters"][0])
        character.update(id="CHAR-LINZHOU", name="林舟")
        self.data["characters"].append(character)
        self.data["shots"][0]["character_ids"].append(character["id"])
        voice = deepcopy(self.voice)
        voice.update(id="VOICE-LINZHOU", name="林舟声音", character_id=character["id"])
        self.data["voices"].append(voice)
        self.prompt["asset_ids"].extend([voice["id"], character["id"]])
        self.prompt["reference_bindings"].append({"slot": "@素材5", "asset_id": voice["id"],
                                                 "audio_reference_id": "video-a"})
        self.prompt["audio_reference_profile"].update(max_files=2, max_total_duration=2.0)
        self.prompt["text"] = "@素材5 参考角色林舟的声音身份与音色。\n" + self.prompt["text"]
        self.prompt["text"] = self.prompt["text"].replace(
            "角色晚晴：参考@素材1", "角色晚晴：声音身份参考@素材5，参考@素材1")
        self.prompt["text"] = self.prompt["text"].replace(
            "场景旧院门：", "角色林舟：声音身份参考@素材4，青年男性。\n场景旧院门：")
        self.assertIn("指向其他角色", self.errors())
        self.prompt["text"] = self.prompt["text"].replace(
            "角色晚晴：声音身份参考@素材5", "角色晚晴：声音身份参考@素材4").replace(
            "角色林舟：声音身份参考@素材4", "角色林舟：声音身份参考@素材5")
        self.assertEqual("", self.errors())

    def test_role_body_cannot_use_image_as_voice_reference(self):
        self.prompt["text"] = self.prompt["text"].replace(
            "角色晚晴：参考@素材1", "角色晚晴：声音身份参考@素材1，参考@素材1")
        self.assertIn("未绑定声音资产", self.errors())

    def test_visual_binding_cannot_select_audio_reference(self):
        self.prompt["reference_bindings"][0]["audio_reference_id"] = "video-a"
        self.assertIn("只有声音绑定", self.errors())

    def test_reference_crop_duration_and_unique_ids_are_checked(self):
        reference = self.voice["references"][0]
        reference["source_end"] = 2.1
        self.assertIn("超出母版", self.errors())
        reference["source_end"] = 1.5
        self.assertIn("副本时长与母版裁剪区间不一致", self.errors())
        reference["source_end"] = 1.0
        self.voice["references"].append(deepcopy(reference))
        self.assertIn("投喂副本 id 重复", self.errors())

    def test_platform_model_and_support_must_match(self):
        profile = self.prompt["audio_reference_profile"]
        profile["supports_voice_reference"] = False
        self.assertIn("不支持声音参考", self.errors())
        profile["supports_voice_reference"] = True
        profile["model_id"] = "another-model"
        self.assertIn("model_id", self.errors())

    def test_platform_count_duration_and_format_budgets(self):
        profile = self.prompt["audio_reference_profile"]
        for key, value, message in (
            ("max_files", 0, "数量超过"),
            ("max_file_duration", 0.5, "单文件时长"),
            ("max_total_duration", 0.5, "总时长"),
            ("formats", ["mp3"], "音频格式"),
        ):
            with self.subTest(key=key):
                original = profile[key]
                profile[key] = value
                self.assertIn(message, self.errors())
                profile[key] = original

    def test_incomplete_model_limits_warn_instead_of_inventing_limits(self):
        self.prompt["audio_reference_profile"].update(max_files=None, formats=[])
        errors, warnings = validate_project(snapshot_dependencies(self.data))
        self.assertFalse(errors)
        self.assertTrue(any("未核验项" in warning for warning in warnings))

    def test_voice_change_only_invalidates_referencing_prompts(self):
        self.voice["revision"] += 1
        self.voice["description"] += " 尾音更短。"
        self.assertEqual(["PROMPT-VIDEO-001"], find_stale_entities(self.data))
        self.assertFalse(validate_project(snapshot_dependencies(self.data))[0])

    def test_shared_voice_sync_preserves_identity_and_invalidates_reference(self):
        changed = deepcopy(self.voice)
        changed.update(revision=2, description="新版声音，字头更清楚。")
        shared = {"voices": [changed]}
        self.assertTrue(validate_shared_assets(self.data, shared))
        synced = sync_shared_assets(self.data, shared)
        self.assertFalse(validate_shared_assets(synced, shared))
        self.assertEqual(["PROMPT-VIDEO-001"], find_stale_entities(synced))
        legacy = load_project(ROOT / "examples/demo/project.json")
        imported = sync_shared_assets(legacy, shared, include_new=True)
        self.assertEqual("1.1", imported["schema_version"])
        self.assertEqual(changed, imported["voices"][0])
        self.assertFalse(validate_project(imported)[0])

    def test_remote_audio_path_is_not_a_local_file(self):
        self.voice["master"]["path"] = "https://example.invalid/master.wav"
        self.assertIn("不能使用远程 URL", self.errors())

    def test_media_duration_and_truncated_wav_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for record in [self.voice["master"], *self.voice["references"]]:
                path = root / record["path"]
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(8000)
                    audio.writeframes(b"\0\0" * int(8000 * record["duration"]))
                record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(([], []), validate_voice_media(self.data, root))
            record = self.voice["references"][0]
            record["duration"] = 0.5
            self.assertTrue(any("实测时长" in error for error in validate_voice_media(self.data, root)[0]))
            record["duration"] = 1.0
            path = root / record["path"]
            path.write_bytes(path.read_bytes()[:-20])
            record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(any("截断" in error for error in validate_voice_media(self.data, root)[0]))
            master = self.voice["master"]
            path = root / master["path"]
            payload = bytearray(path.read_bytes())
            payload[24:28] = b"\0" * 4
            path.write_bytes(payload)
            master["sha256"] = hashlib.sha256(payload).hexdigest()
            self.assertTrue(any("采样率" in error for error in validate_voice_media(self.data, root)[0]))


if __name__ == "__main__":
    unittest.main()
