"""Video-model voice references export as assets, never as scripted dialogue."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
import wave

from scripts.project_data import load_project, snapshot_dependencies
from scripts.qc_check import extract_prompt_blocks
from scripts.render_project import build_wan_visual_prompt, export_project, render_documents


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo" / "project.json"


def planned_voice():
    return {
        "id": "VOICE-WANQING", "revision": 1, "name": "晚晴常态声音",
        "character_id": "CHAR-WANQING", "description": "清亮偏实声，字头清楚，句尾自然收住。",
        "language": "普通话", "source": "测试中的待制作声音设计", "status": "planned",
        "audition": "unreviewed", "master": None, "references": [], "notes": "",
    }


def write_test_wave(path, seconds):
    """Synthetic silence is a temporary file-format fixture, not a character sample."""
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * int(8000 * seconds))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VoiceReferenceExportTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)
        self.data.pop("voices", None)
        for prompt in self.data["prompts"]:
            prompt.pop("audio_reference_profile", None)
        self.data = snapshot_dependencies(self.data)

    def ready_data(self, root):
        voice = planned_voice()
        master_hash = write_test_wave(root / "master.wav", 2)
        reference_hash = write_test_wave(root / "reference.wav", 1)
        transcript = "这段样片文字只用于资产核对。"
        voice.update(status="ready", audition="approved", source="临时合成 WAV 测试夹具")
        voice["master"] = {
            "path": "master.wav", "sha256": master_hash, "duration": 2.0,
            "transcript": transcript,
        }
        voice["references"] = [{
            "id": "video-reference", "model_id": "test-video-audio-v1", "path": "reference.wav",
            "sha256": reference_hash, "duration": 1.0, "source_start": 0.0, "source_end": 1.0,
            "transcript": transcript,
        }]
        self.data["schema_version"] = "1.1"
        self.data["voices"] = [voice]
        prompt = next(item for item in self.data["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        prompt["audio_reference_profile"] = {
            "model_id": "test-video-audio-v1", "supports_voice_reference": True,
            "max_files": 1, "max_file_duration": 1.0, "max_total_duration": 1.0,
            "formats": ["wav"], "source": "测试配置，不代表厂商规格",
        }
        prompt["asset_ids"].append(voice["id"])
        prompt["reference_bindings"].append({
            "slot": "@素材4", "asset_id": voice["id"], "audio_reference_id": "video-reference",
        })
        prompt["text"] = (
            "@素材4 参考角色晚晴的声音身份、口音与咬字。禁止继承样片台词、情绪、背景声。\n"
            + prompt["text"]
        )
        return snapshot_dependencies(self.data)

    def test_legacy_project_keeps_dual_blocks_and_has_no_voice_upload_table(self):
        documents = render_documents(self.data)
        shot = documents["SHOT-001_分镜.md"]
        self.assertIn("### 即梦 Seedance 全模态版", shot)
        self.assertIn("```wan\n", shot)
        self.assertNotIn("本镜音频上传槽", shot)
        self.assertNotIn("角色声音参考资产库", documents["project.md"])

    def test_planned_voice_is_actionable_but_does_not_create_upload_slots(self):
        self.data["schema_version"] = "1.1"
        self.data["voices"] = [planned_voice()]
        documents = render_documents(snapshot_dependencies(self.data))
        project = documents["project.md"]
        shot = documents["SHOT-001_分镜.md"]
        self.assertIn("VOICE-WANQING", project)
        self.assertIn("待制作；不可投喂", project)
        self.assertIn("试听制作说明", project)
        self.assertIn("未绑定；不上传", shot)
        self.assertNotIn("### 本镜音频上传槽", shot)
        self.assertNotIn("@素材4", shot)

    def test_ready_reference_uses_target_model_and_preserves_formal_dialogue(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = self.ready_data(Path(temporary))
            before = deepcopy(data)
            documents = render_documents(data)
            shot = documents["SHOT-001_分镜.md"]
            self.assertIn("### test-video-audio-v1 · 目标模型动态提示词", shot)
            self.assertNotIn("```wan\n", shot)
            self.assertNotIn("### 即梦 Seedance", shot)
            self.assertIn("| @素材4 | VOICE-WANQING | 晚晴 | test-video-audio-v1 |", shot)
            self.assertIn("reference.wav", shot)
            self.assertIn("| LINE-LOCK | 1 | 0.0–5.0s | 2.5–4.0s |", shot)
            transcript = data["voices"][0]["master"]["transcript"]
            self.assertIn(transcript, documents["project.md"])
            blocks = [block for document in documents.values()
                      for block in extract_prompt_blocks(document)[0]]
            self.assertEqual(len(blocks), len(data["prompts"]))
            self.assertFalse(any(transcript in block["text"] for block in blocks))
            source = documents["project.md"].split("## 剧本节拍与原始台词", 1)[1].split("## 静态资产总库", 1)[0]
            self.assertNotIn(transcript, source)
            self.assertEqual(before, data)

    def test_silent_character_voice_stays_global_and_is_not_loaded_by_shot(self):
        voice = planned_voice()
        voice.update(id="VOICE-SILENT", character_id="CHAR-SILENT", name="旁观者声音")
        self.data["schema_version"] = "1.1"
        self.data["voices"] = [voice]
        character = deepcopy(self.data["characters"][0])
        character.update(id="CHAR-SILENT", name="旁观者")
        self.data["characters"].append(character)
        self.data["shots"][0]["character_ids"].append("CHAR-SILENT")
        prompt = next(item for item in self.data["prompts"] if item["id"] == "PROMPT-VIDEO-001")
        prompt["asset_ids"].append("CHAR-SILENT")
        documents = render_documents(snapshot_dependencies(self.data))
        self.assertIn("VOICE-SILENT", documents["project.md"])
        self.assertNotIn("VOICE-SILENT", documents["SHOT-001_分镜.md"])

    def test_media_check_blocks_all_writes_on_changed_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = self.ready_data(root)
            (root / "reference.wav").write_bytes(b"changed after capture")
            output = root / "delivery"
            with self.assertRaises(ValueError):
                export_project(data, output, media_root=root)
            self.assertFalse(output.exists())

    def test_export_does_not_copy_audio_and_preserves_manual_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = self.ready_data(root)
            output = root / "delivery"
            export_project(data, output, media_root=root)
            self.assertFalse(list(output.glob("*.wav")))
            shot = output / "SHOT-001_分镜.md"
            shot.write_text(shot.read_text(encoding="utf-8") + "\n手工审阅意见。\n", encoding="utf-8")
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaisesRegex(ValueError, "被手工修改"):
                export_project(data, output, media_root=root)
            self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})

    def test_explicit_visual_fallback_removes_audio_slot_and_its_instructions(self):
        text = (
            "@素材4 参考角色晚晴的声音身份。禁止继承样片台词与背景声。\n"
            "声音身份：参考@素材4，保持音色。\n"
            "角色晚晴：窄脸，灰蓝长衫，声音参考@素材4。\n"
            "镜头1（0.0-5.0s）：人物面部在左，手停在门边。\n--ar 9:16"
        )
        visual = build_wan_visual_prompt(text, ["@素材4"])
        self.assertNotIn("@素材4", visual)
        self.assertNotIn("声音身份", visual)
        self.assertNotIn("样片台词", visual)
        self.assertIn("灰蓝长衫", visual)


if __name__ == "__main__":
    unittest.main()
