"""Audio cue exports and malformed export manifests retain safe behavior."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.project_data import load_project, snapshot_dependencies
from scripts.render_project import export_project, main as render_main, render_documents


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo" / "project.json"


class AudioExportRegressionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project(DEMO)
        # Exercise legacy projects even after the maintained demo gains cues.
        for shot in self.data["shots"]:
            for segment in shot["segments"]:
                for line in segment["lines"]:
                    line.pop("start", None)
                    line.pop("end", None)

    def captured(self):
        return snapshot_dependencies(self.data)

    def test_single_segment_exports_each_dialogue_os_and_narration_cue(self):
        original = deepcopy(self.data)
        for kind in ("os", "narration"):
            with self.subTest(kind=kind):
                self.data = deepcopy(original)
                extra = deepcopy(self.data["dialogues"][0])
                extra.update(id="LINE-EXTRA", kind=kind, text="别动。")
                if kind == "narration":
                    extra["speaker_id"] = None
                self.data["dialogues"].insert(1, extra)
                segment = self.data["shots"][0]["segments"][0]
                segment["lines"][0].update(start=2.5, end=4.0)
                segment["lines"].append({"dialogue_id": "LINE-EXTRA", "text": "别动。",
                                         "start": 4.0, "end": 4.8})
                prompt = next(p for p in self.data["prompts"] if p["id"] == "PROMPT-VIDEO-001")
                marker = "4.0–5.0秒嘴唇合拢"
                cue_type = "OS" if kind == "os" else "NAR"
                prompt["text"] = prompt["text"].replace(
                    marker, f"4.0–4.8秒，{cue_type}，清亮女中音，平缓地说：“别动。”\n{marker}")
                text = render_documents(self.captured())["SHOT-001_分镜.md"]
                self.assertIn("| 起始镜头 | 所属镜头区间 | 发声区间（片段局部） |", text)
                self.assertIn("| LINE-LOCK | 1 | 0.0–5.0s | 2.5–4.0s | 晚晴 | dialogue |", text)
                speaker = "晚晴" if kind == "os" else "旁白"
                self.assertIn(f"| LINE-EXTRA | 1 | 0.0–5.0s | 4.0–4.8s | {speaker} | {kind} |", text)

    def test_legacy_delivery_cues_are_explicitly_uncalibrated(self):
        documents = render_documents(self.captured())
        self.assertIn("| LINE-LOCK | 1 | 0.0–5.0s | 未标定 |", documents["SHOT-001_分镜.md"])
        self.assertIn("| LINE-KEY | 1 | 0.0–5.0s | 未标定 |", documents["SHOT-002_分镜.md"])

    def test_audio_cue_can_continue_into_following_physical_shot(self):
        shot = self.data["shots"][0]
        first = shot["segments"][0]
        first["end"] = 3.0
        first["lines"][0].update(start=2.5, end=4.0)
        second = {"index": 2, "start": 3.0, "end": 5.0,
                  "description": "对白在画外延续，观察门锁至片段结束。", "lines": []}
        shot["segments"].append(second)
        prompt = next(p for p in self.data["prompts"] if p["id"] == "PROMPT-VIDEO-001")
        prompt["text"] = prompt["text"].replace("单镜头5秒", "多切镜5秒").replace(
            "镜头1（0.0-5.0s）：", "镜头1（0.0-3.0s）：").replace(
            "4.0–5.0秒嘴唇合拢", "镜头2（3.0-5.0s）：晚晴的声音在画外延续到4.0秒。4.0–5.0秒嘴唇合拢")
        text = render_documents(self.captured())["SHOT-001_分镜.md"]
        self.assertIn("| LINE-LOCK | 1 | 0.0–3.0s | 2.5–4.0s |", text)
        self.assertEqual(text.count("| LINE-LOCK |"), 1)

    def test_nonobject_manifest_cli_reports_error_without_writing(self):
        for malformed in ([], None, "manifest", 7, False):
            with self.subTest(manifest=malformed), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                output = directory / "output"
                export_project(self.captured(), output)
                manifest = output / ".drama-export.json"
                manifest.write_text(json.dumps(malformed), encoding="utf-8")
                before = {path.name: path.read_bytes() for path in output.iterdir()}
                project = directory / "project.json"
                project.write_text(json.dumps(self.captured(), ensure_ascii=False), encoding="utf-8")
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    status = render_main([str(project), "--output", str(output)])
                self.assertEqual(status, 1)
                self.assertIn("ERROR: 导出清单根节点必须是对象", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})


if __name__ == "__main__":
    unittest.main()
