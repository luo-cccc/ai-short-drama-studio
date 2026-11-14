"""视频声音参考的文本隔离、角色绑定和本地媒体检查。"""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

from scripts.project_data import load_project, snapshot_dependencies
from scripts.qc_check import check, check_project, main


ROOT = Path(__file__).resolve().parents[1]
DECLARATION = (
    "@素材4 参考角色晚晴的声音身份，音色与咬字。"
    "禁止继承样片台词，情绪与场景环境音。"
)


def voice_project():
    data = load_project(ROOT / "examples/demo/project.json")
    data["schema_version"] = "1.1"
    voice = {
        "id": "VOICE-WANQING", "revision": 1, "name": "晚晴常态声音",
        "character_id": "CHAR-WANQING", "description": "清亮女中音，咬字清楚。",
        "language": "zh-CN", "source": "单元测试数据，不作为真实声音资产。",
        "status": "ready",
        "reference": {
            "model_id": "test-video-model",
            "path": "voices/reference.wav", "sha256": "0" * 64,
            "duration": 1.0,
            "transcript": "今天风很轻。",
        },
        "notes": "",
    }
    data["voices"] = [voice]
    prompt = next(p for p in data["prompts"] if p["id"] == "PROMPT-VIDEO-001")
    prompt["text"] = DECLARATION + "\n" + prompt["text"]
    prompt["text"] = prompt["text"].replace("角色晚晴：参考@素材1", "角色晚晴：声音身份参考@素材4，参考@素材1")
    prompt["reference_bindings"].append({
        "slot": "@素材4", "asset_id": voice["id"],
    })
    prompt["asset_ids"].append(voice["id"])
    prompt["audio_reference_profile"] = {
        "model_id": "test-video-model", "supports_voice_reference": True,
        "max_files": 2, "max_file_duration": 5.0, "max_total_duration": 10.0,
        "formats": ["wav"], "source": "单元测试配置，不代表任何实际平台能力。",
    }
    prompt["revision"] += 1
    return snapshot_dependencies(data)


def project_errors(data, **kwargs):
    return [error for result in check_project(data, **kwargs) for error in result["errors"]]


def write_fixture_media(data, directory):
    """只为文件验证生成一秒静音WAV，不交付为声音样片。"""
    record = data["voices"][0]["reference"]
    target = Path(directory) / record["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000)
    record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return snapshot_dependencies(data)


class VoiceReferenceTextTests(unittest.TestCase):
    def text(self):
        data = load_project(ROOT / "examples/demo/project.json")
        return next(p["text"] for p in data["prompts"] if p["id"] == "PROMPT-VIDEO-001")

    def test_voice_reference_is_not_checked_as_visual_scene_inheritance(self):
        declaration = "@素材4 参考声音身份与咬字，样片场景环境声不作为本镜声场。"
        errors, _ = check(declaration + "\n" + self.text(), duration=5, template="T9")
        self.assertFalse(errors, errors)

    def test_voice_reference_cannot_hide_a_visual_scene_declaration(self):
        declaration = "@素材4 参考场景空间布局，并参考声音身份。"
        errors, _ = check(declaration + "\n" + self.text(), duration=5, template="T9")
        self.assertTrue(any("动态场景/故事板参考" in error for error in errors), errors)

    def test_audio_uses_dynamic_material_slot(self):
        errors, _ = check(DECLARATION.replace("@素材4", "@图片4") + "\n" + self.text(), duration=5, template="T9")
        self.assertTrue(any("声音参考须使用动态素材位" in error for error in errors), errors)

    def test_static_prompt_rejects_voice_reference(self):
        errors, _ = check(DECLARATION + "\n生成角色参考图。\n--ar 16:9", mode="static", duration=None, template="T1")
        self.assertTrue(any("声音参考仅用于动态" in error for error in errors), errors)

    def test_reference_transcript_is_not_a_prompt_dialogue(self):
        declaration = DECLARATION + "试听台词：“今天风很轻。”"
        errors, _ = check(declaration + "\n" + self.text(), duration=5, template="T9")
        self.assertTrue(any("试听文本" in error for error in errors), errors)


class VoiceReferenceProjectTests(unittest.TestCase):
    def test_ready_reference_passes_without_claiming_local_media_check(self):
        data = voice_project()
        self.assertFalse(project_errors(data))
        self.assertEqual(len(data["dialogues"]), 2)
        self.assertFalse(any(line["text"] == "今天风很轻。" for line in data["dialogues"]))

    def test_reference_transcript_in_prompt_is_rejected_by_dialogue_accounting(self):
        data = voice_project()
        prompt = next(p for p in data["prompts"] if p["id"] == "PROMPT-VIDEO-001")
        prompt["text"] = '试听：“今天风很轻。”\n' + prompt["text"]
        data = snapshot_dependencies(data)
        errors = project_errors(data)
        self.assertTrue(any("首个镜头之前" in error for error in errors), errors)

    def test_local_media_validation_is_explicit_and_detects_missing_files(self):
        data = voice_project()
        self.assertFalse(project_errors(data))
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(project_errors(data, media_root=directory))
            data = write_fixture_media(data, directory)
            self.assertFalse(project_errors(data, media_root=directory))

    def test_media_fingerprint_change_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            data = write_fixture_media(voice_project(), directory)
            target = Path(directory) / data["voices"][0]["reference"]["path"]
            with target.open("ab") as output:
                output.write(b"changed")
            errors = project_errors(data, media_root=directory)
            self.assertTrue(any("指纹" in error or "SHA" in error or "sha256" in error for error in errors), errors)

    def test_cli_media_root_checks_json_project(self):
        with tempfile.TemporaryDirectory() as directory:
            data = write_fixture_media(voice_project(), directory)
            project_path = Path(directory) / "project.json"
            project_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                status = main([str(project_path), "--media-root", directory, "--format", "json"])
            self.assertEqual(status, 0, buffer.getvalue())
            self.assertTrue(json.loads(buffer.getvalue())["ok"])
            (Path(directory) / data["voices"][0]["reference"]["path"]).unlink()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(project_path), "--media-root", directory]), 1)

    def test_cli_media_root_rejects_text_input(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["prompt.txt", "--media-root", "."])
        self.assertEqual(caught.exception.code, 2)

    def test_legacy_project_has_no_media_requirement(self):
        data = load_project(ROOT / "examples/demo/project.json")
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(project_errors(data, media_root=directory))


if __name__ == "__main__":
    unittest.main()
