"""标题上下文、镜头声明边界与项目对白对账的回归。"""
from __future__ import annotations

from pathlib import Path
import unittest

from scripts.project_data import load_project, snapshot_dependencies
from scripts.qc_check import check, check_project, parse_timestamps, scan_document


ROOT = Path(__file__).resolve().parents[1]


def dynamic_text():
    return "\n".join([
        "生成一段多切镜5秒的剧情短片，同步生成配音和环境音。",
        "角色林舟：黑色短发，灰色长衣。",
        "场景：前景石阶，中景木门，背景院墙。",
        "整体情绪为疑惑，释然。",
        "写实画面风格，柔和侧光，青灰色彩，木纹质感。",
        "环境音：脚步声。",
        "BGM：低音弦乐。",
        "镜头1（0.0-2.5s）：林舟停在门旁，低声说：“别动。”",
        "镜头2（2.5-5.0s）：林舟手掌按住门扇，NAR：“门关上了。”",
        "木门轮廓清晰，衣袖沿手臂垂落，手指紧贴门栓，石阶纹理连贯，背景院墙位置稳定。",
        "--ar 16:9",
    ])


class HeadingContextRegressions(unittest.TestCase):
    def block(self, headings, text, language="text", metadata=None):
        return "\n".join([
            *headings,
            *([metadata, "  "] if metadata else []),
            f"```{language}", text, "```",
        ])

    def test_nearer_dynamic_template_cannot_be_hidden_by_static_ancestor(self):
        text = dynamic_text().replace("2.5-5.0", "2.5-4.5")
        result = scan_document(self.block([
            "# Template 1 静态资产", "  ## Template 9 动态视频", "### 提示词",
        ], text), "nested.md")[0]
        self.assertEqual((result["template"], result["mode"]), ("T9", "dynamic"))
        self.assertTrue(any("总时长" in error for error in result["errors"]))

    def test_nearer_static_template_cannot_be_hidden_by_dynamic_ancestor(self):
        result = scan_document(self.block([
            "# 模板9 动态视频", "## 模板 1 静态角色", "### 提示词",
        ], "生成角色参考图，灰衣垂落。\n--ar 16:9"), "nested.md")[0]
        self.assertEqual((result["template"], result["mode"]), ("T1", "static"))
        self.assertFalse(result["errors"])

    def test_nearest_mode_heading_does_not_inherit_conflicting_template(self):
        for outer, inner, text, expected in [
            ("# Template 9 动态视频", "## 静态资产", "生成角色参考图。", "static"),
            ("# Template 1 静态资产", "## 动态视频", dynamic_text(), "dynamic"),
        ]:
            with self.subTest(expected=expected):
                result = scan_document(self.block([outer, inner, "### 正文"], text))[0]
                self.assertIsNone(result["template"])
                self.assertEqual(result["mode"], expected)
                self.assertFalse(result["errors"])

    def test_explicit_fence_mode_and_mixed_heading_remain_usable(self):
        for heading, language, text in [
            ("# 静态资产", "dynamic", dynamic_text()),
            ("# 动态视频", "static", "生成角色参考图。"),
            ("# 静态与动态提示词", "text", "生成角色参考图。"),
        ]:
            with self.subTest(heading=heading, language=language):
                result = scan_document(self.block([heading], text, language))[0]
                self.assertEqual(result["mode"], "dynamic" if language == "dynamic" else "static")
                self.assertFalse(result["errors"])

    def test_block_metadata_still_overrides_nearest_title_and_fence(self):
        for template, headings, language, text, expected in [
            ("T9", ["# Template 9", "## Template 1 静态资产"], "static", dynamic_text(), "dynamic"),
            ("T1", ["# Template 1", "## Template 9 动态视频"], "dynamic", "生成角色参考图。", "static"),
        ]:
            with self.subTest(template=template):
                metadata = f'  <!-- prompt id=PROMPT-TEST template="{template}"' + (' duration="5.0"' if template == "T9" else '') + ' -->'
                result = scan_document(self.block(headings, text, language, metadata))[0]
                self.assertEqual((result["template"], result["mode"]), (template, expected))
                self.assertEqual(result["prompt_id"], "PROMPT-TEST")
                self.assertFalse(result["errors"])


class TimestampCandidateRegressions(unittest.TestCase):
    def test_natural_camera_continuations_are_not_extra_shot_declarations(self):
        text = dynamic_text().replace(
            "镜头2（", "镜头继续贴近门闩，木纹留在画面右侧。\n镜头一边平移，一边保持门扇在中景。\n镜头第一次轻移，门闩从画面右侧移到中间。\n\t镜头缓缓推进。\n镜头2（"
        )
        stamps, errors = parse_timestamps(text, 5)
        self.assertEqual(len(stamps), 2)
        self.assertFalse(errors)
        self.assertFalse(check(text, duration=5)[0])

    def test_malformed_numbered_and_placeholder_declarations_are_still_errors(self):
        for header in [
            "镜头1（0..0-x.0s）：", "镜头1（NaN-2.5s）：", "镜头1：",
            "镜头一（0.0-2.5s）：", "镜头N（0.0-2.5s）：", "镜头 1（0.0-2.5s）：",
            "镜头1 （0.0-2.5s）：", "镜头0（0.0-2.5s）：", "镜头（0.0-2.5s）：",
            "镜头1（0-2.5s）：", "镜头1（0.00-2.50s）：", "镜头1（0.0-2.5s）:",
            "镜头第2（0.0-2.5s）：", "镜头第二（0.0-2.5s）：", "镜头 第 二 （0.0-2.5s）：",
            "镜头第N（0.0-2.5s）：",
        ]:
            with self.subTest(header=header):
                text = dynamic_text().replace("镜头1（0.0-2.5s）：", header)
                errors = parse_timestamps(text, 5)[1]
                self.assertTrue(any("时间戳格式非法" in error for error in errors), errors)
                appended = dynamic_text() + "\n" + header + "木门关闭。"
                errors = parse_timestamps(appended, 5)[1]
                self.assertTrue(any("时间戳格式非法" in error for error in errors), errors)

    def test_indented_valid_headers_preserve_offsets_and_total(self):
        text = dynamic_text().replace("镜头1（", " \t镜头1（").replace("镜头2（", "  镜头2（")
        stamps, errors = parse_timestamps(text, 5)
        self.assertFalse(errors)
        self.assertEqual([stamp["index"] for stamp in stamps], [1, 2])
        self.assertTrue(text[stamps[0]["text_offset"]:].startswith("林舟停在门旁"))

    def test_timestamp_like_text_inside_multiline_dialogue_is_not_a_header(self):
        text = dynamic_text().replace("别动。", "你看，\n镜头一（示例）：写在这里。\n请照做。")
        stamps, errors = parse_timestamps(text, 5)
        self.assertEqual(len(stamps), 2)
        self.assertFalse(errors)
        self.assertFalse(check(text, duration=5)[0])


class ProjectDialogueBoundaryRegressions(unittest.TestCase):
    def project(self, transform):
        data = load_project(ROOT / "examples" / "demo" / "project.json")
        prompt = next(prompt for prompt in data["prompts"] if prompt["template"] == "T9")
        prompt["text"] = transform(prompt["text"])
        prompt["revision"] += 1
        return snapshot_dependencies(data)

    def errors(self, data):
        return [error for result in check_project(data) for error in result["errors"]]

    def test_extra_dialogue_and_narration_before_first_shot_are_rejected(self):
        for prefix in ['NAR：“额外的旁白。”\n', '晚晴说："额外台词。"\n', 'OS：“额外\n独白。”\n']:
            with self.subTest(prefix=prefix):
                errors = self.errors(self.project(lambda text: prefix + text))
                self.assertTrue(any("首个镜头之前" in error for error in errors), errors)

    def test_extra_tail_dialogue_is_still_rejected(self):
        for cue in ["NAR", "晚晴说"]:
            with self.subTest(cue=cue):
                data = self.project(lambda text: text.replace("--ar ", f'{cue}：“额外台词。”\n--ar '))
                self.assertTrue(any("台词文字或顺序不一致" in error for error in self.errors(data)))

    def test_unquoted_setup_and_camera_continuation_do_not_add_dialogue(self):
        def transform(text):
            text = "\n \t\n画内文字：门牌内容交给后期制作。\n" + text
            first_shot = text.index("镜头1（")
            end = text.find("\n", first_shot)
            return text[:end] + "\n镜头继续贴近门闩，木纹留在画面右侧。" + text[end:]

        self.assertFalse(self.errors(self.project(transform)))

    def test_multiline_spoken_os_and_narration_keep_project_dialogue_accounting(self):
        for cue, kind in [("低声说", "dialogue"), ("OS", "os"), ("NAR", "narration")]:
            with self.subTest(cue=cue):
                data = load_project(ROOT / "examples" / "demo" / "project.json")
                line = data["dialogues"][0]
                previous, utterance = line["text"], "你就是按\n模板做事的人。"
                line.update(text=utterance, kind=kind, revision=line["revision"] + 1)
                for shot in data["shots"]:
                    for segment in shot["segments"]:
                        for delivery in segment["lines"]:
                            if delivery["dialogue_id"] == line["id"]:
                                delivery["text"] = utterance
                                shot["revision"] += 1
                for prompt in data["prompts"]:
                    if prompt["template"] in {"T7", "T8", "T9"} and previous in prompt["text"]:
                        prompt["text"] = prompt["text"].replace('“' + previous + '”', '\n' + cue + '：“' + utterance + '”')
                        prompt["revision"] += 1
                self.assertFalse(self.errors(snapshot_dependencies(data)))


if __name__ == "__main__":
    unittest.main()
