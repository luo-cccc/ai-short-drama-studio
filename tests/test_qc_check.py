"""QC 的可观察行为回归：逐块隔离、时间戳、引用与项目对账。"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import qc_check as qc


def dynamic_text() -> str:
    return "\n".join([
        "生成一段多切镜10秒的剧情短片。同步生成配音和环境音。",
        "角色林舟：黑色短发，灰色长衣。",
        "场景：前景石阶，中景木门，背景院墙，远景屋顶。",
        "整体情绪为紧张，疑惑，释然。",
        "中国水墨动画风格，柔和侧光照亮角色，深灰与暖白色彩，纸纹质感。",
        "环境音：石阶上的脚步声。",
        "BGM：低音弦乐。",
        "镜头1（0.0-5.0s）：镜头平移，林舟停在木门旁，低声匀速说：\"别动。\"",
        "镜头2（5.0-10.0s）：镜头缓缓推进，林舟手指落在门栓上，平缓说：\"我看见了。\"",
        "木门轮廓清晰，人物衣袖沿手臂垂落，手指紧贴门栓，石阶纹理连贯，背景院墙位置稳定。",
        "--ar 16:9",
    ])


class PromptChecks(unittest.TestCase):
    def test_mixed_markdown_checks_only_independent_prompt_blocks(self):
        document = "\n".join([
            "# Template 9 制作说明 [管理备注]",
            "这里的首帧、模板、[待补全]只是管理文本。",
            "```json", '{"示例": "镜头1（坏时间戳）"}', "```",
            "## 第二章 静态资产",
            "<!-- prompt id=PROMPT-SPACE template=T5 -->",
            "```text", "生成九宫格空间图。" + "石墙轮廓清楚。" * 100, "--ar 16:9", "```",
            "## 第三章 动态视频",
            "<!-- prompt id=PROMPT-VIDEO template=T9 duration=10.0 -->",
            "```text", dynamic_text(), "```",
        ])
        results = qc.scan_document(document, "shot.md")
        self.assertEqual([r["template"] for r in results], ["T5", "T9"])
        self.assertEqual([r["mode"] for r in results], ["static", "dynamic"])
        self.assertFalse([e for r in results for e in r["errors"]])

    def test_management_only_blocks_are_explicitly_skipped(self):
        results = qc.scan_document("# 管理数据\n```json\n{}\n```", "notes.md")
        self.assertTrue(results[0]["skipped"])
        self.assertTrue(results[0]["warnings"])

    def test_unfenced_markdown_planning_is_not_scanned_as_a_prompt(self):
        source = "# Template 9 制作说明\n角色：[角色名称]\n场景：[场景名称]\n"
        results = qc.scan_document(source, "planning.md")
        self.assertTrue(results[0]["skipped"])
        self.assertFalse(results[0]["errors"])

    def test_first_timestamp_must_start_at_zero(self):
        errors, _ = qc.check(dynamic_text().replace("0.0-5.0", "2.0-5.0"), duration=10)
        self.assertTrue(any("0.0秒" in error for error in errors))

    def test_timestamp_requires_exactly_one_decimal_and_colon(self):
        for replacement in ["镜头1（0-5s）：", "镜头1（0.00-5.00s）：", "镜头1（0.0-5.0s）:"]:
            with self.subTest(replacement=replacement):
                errors, _ = qc.check(dynamic_text().replace("镜头1（0.0-5.0s）：", replacement), duration=10)
                self.assertTrue(any("格式非法" in error for error in errors))

    def test_malformed_timestamp_returns_errors_instead_of_crashing(self):
        for replacement in ["镜头1（0..0-x.0s）：", "镜头1（NaN-5.0s）：", "镜头1："]:
            with self.subTest(replacement=replacement):
                errors, _ = qc.check(dynamic_text().replace("镜头1（0.0-5.0s）：", replacement), duration=10)
                self.assertTrue(errors)

    def test_timestamp_gap_overlap_sequence_and_duration_are_reported(self):
        variants = [
            ("5.0-10.0", "6.0-10.0", "断裂"),
            ("5.0-10.0", "4.0-10.0", "重叠"),
            ("镜头2（", "镜头3（", "序号"),
            ("5.0-10.0", "5.0-9.0", "总时长"),
        ]
        for old, new, expected in variants:
            with self.subTest(expected=expected):
                errors, _ = qc.check(dynamic_text().replace(old, new), duration=10)
                self.assertTrue(any(expected in error for error in errors))

    def test_duration_and_template_metadata_are_per_block(self):
        document = "\n".join([
            "<!-- prompt id=PROMPT-A template=T9 duration=10.0 -->", "```text", dynamic_text(), "```",
            "<!-- prompt id=PROMPT-B template=T9 duration=11.0 -->", "```text", dynamic_text(), "```",
        ])
        first, second = qc.scan_document(document)
        self.assertFalse(first["errors"])
        self.assertTrue(any("规定时长" in e for e in second["errors"]))

    def test_emotion_target_is_required_but_its_words_are_legal(self):
        errors, warnings = qc.check(dynamic_text(), duration=10)
        self.assertFalse(errors)
        self.assertFalse(any("紧张" in w or "疑惑" in w for w in warnings))
        errors, _ = qc.check(dynamic_text().replace("整体情绪为紧张，疑惑，释然。\n", ""), duration=10)
        self.assertTrue(any("④" in e for e in errors))

    def test_style_recognition_is_advisory(self):
        source = dynamic_text().replace("中国水墨动画风格，柔和侧光照亮角色，深灰与暖白色彩，纸纹质感。\n", "")
        errors, warnings = qc.check(source, duration=10)
        self.assertFalse(errors)
        self.assertTrue(any("⑤" in warning for warning in warnings))

    def test_every_used_reference_slot_requires_its_own_declaration(self):
        source = "@素材1 参考角色外观。禁止继承背景、光影、色彩。\n" + dynamic_text().replace("角色林舟：", "角色林舟：参考@素材1@素材2，")
        errors, _ = qc.check(source, duration=10)
        self.assertTrue(any("@素材2" in e and "没有" in e for e in errors))
        self.assertFalse(any("@素材1" in e and "没有" in e for e in errors))

    def test_static_length_is_advisory_and_layout_has_no_hard_limit(self):
        self.assertFalse(qc.check("生成角色图。" * 200, mode="static", template="T1")[0])
        errors, warnings = qc.check("【左栏】物理镜头说明。" + "石墙纹理清楚。" * 200, mode="static", template="T6")
        self.assertFalse(errors)
        self.assertFalse(any("500" in w for w in warnings))

    def test_t6b_rejects_positive_reference_color_light_and_style(self):
        for inheritance in ["角色外观、服饰与画面风格", "场景空间布局、色彩光影", "场景颜色与布光", "角色轮廓与渲染风格"]:
            with self.subTest(inheritance=inheritance):
                source = f"@图片1 参考{inheritance}。禁止继承构图、景别。\n生成黑白线稿故事版。\n--ar 16:9"
                errors, _ = qc.check(source, mode="static", template="T6B")
                self.assertTrue(any("T6B参考范围正向继承" in error for error in errors))

    def test_t6b_allows_canonical_shape_only_reference_and_exclusion(self):
        source = "\n".join([
            "@图片1 参考角色五官结构、服装轮廓、体型比例。只取造型结构，不取颜色、光影、渲染风格。",
            "@图片2 参考场景的空间布局、相对方位与陈设位置。只取造型结构，不取颜色、光影、画面风格。",
            "生成黑白线稿故事版。", "--ar 16:9",
        ])
        errors, warnings = qc.check(source, mode="static", template="T6B")
        self.assertFalse(errors)
        self.assertFalse(any("T6B参考范围" in warning for warning in warnings))

    def test_t6b_allows_explicit_inline_negative_scope(self):
        source = "@图片1 参考场景空间布局，只取造型结构，不取颜色、光影、画面风格。禁止继承画面风格、光影、色彩。\n生成黑白线稿故事版。\n--ar 16:9"
        errors, warnings = qc.check(source, mode="static", template="T6B")
        self.assertFalse(errors)
        self.assertFalse(any("T6B参考范围" in warning for warning in warnings))

    def test_t6b_complex_negative_scope_is_review_warning_not_false_error(self):
        source = "@图片1 参考场景空间布局，画面风格并不沿用原图。\n生成黑白线稿故事版。\n--ar 16:9"
        errors, warnings = qc.check(source, mode="static", template="T6B")
        self.assertFalse(errors)
        self.assertTrue(any("复杂否定" in warning for warning in warnings))

    def test_t6b_catches_positive_inheritance_in_followup_sentence(self):
        source = "@图片1 参考场景空间布局。并继承画面风格。\n生成黑白线稿故事版。\n--ar 16:9"
        errors, _ = qc.check(source, mode="static", template="T6B")
        self.assertTrue(any("T6B参考范围正向继承" in error for error in errors))

    def test_color_storyboard_keeps_its_reference_style_scope(self):
        source = "@图片1 参考场景空间布局、色彩光影与画面风格。禁止继承构图、景别。\n生成彩色故事版。\n--ar 16:9"
        errors, _ = qc.check(source, mode="static", template="T6")
        self.assertFalse(errors)

    def test_dynamic_scene_reference_keeps_its_inheritance_restrictions(self):
        source = "@素材1 参考场景空间布局。禁止继承构图、景别。\n" + dynamic_text()
        errors, _ = qc.check(source, mode="dynamic", duration=10, template="T9")
        self.assertTrue(any("动态场景/故事板参考缺少" in error for error in errors))

    def test_invalid_duration_metadata_is_a_diagnostic(self):
        document = "<!-- prompt id=PROMPT-X template=T9 duration=nan -->\n```text\n" + dynamic_text() + "\n```"
        results = qc.scan_document(document)
        self.assertTrue(any("duration" in e for e in results[0]["errors"]))

    def test_metadata_wins_over_surrounding_heading(self):
        document = "## 静态资产\n<!-- prompt id=PROMPT-X template=T9 duration=10 -->\n```text\n" + dynamic_text() + "\n```"
        self.assertEqual(qc.scan_document(document)[0]["mode"], "dynamic")

    def test_unclosed_prompt_fence_is_not_silently_accepted(self):
        results = qc.scan_document("```text\n" + dynamic_text())
        self.assertTrue(any("未闭合" in e for e in results[0]["errors"]))


class ProjectPromptChecks(unittest.TestCase):
    def setUp(self):
        # 这里隔离文本 QC，数据形状与引用关系由 project_data 的独立测试负责。
        fake = types.SimpleNamespace(
            validate_project=lambda data, previous=None: ([], []),
            validate_shape=lambda data: [],
            parse_project=json.loads,
            normalize_dialogue=lambda text: "".join(c for c in text if c.isalnum()),
        )
        self.module_patch = patch.dict(sys.modules, {"project_data": fake})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.data = {
            "shots": [{"id": "SHOT-A", "segments": [
                {"index": 1, "start": 0.0, "end": 5.0, "lines": [{"dialogue_id": "LINE-A", "text": "别动。"}]},
                {"index": 2, "start": 5.0, "end": 10.0, "lines": [{"dialogue_id": "LINE-B", "text": "我看见了。"}]},
            ]}],
            "prompts": [{"id": "PROMPT-A", "template": "T9", "duration": 10, "shot_id": "SHOT-A", "text": dynamic_text()}],
        }

    def test_each_project_prompt_is_checked_with_its_identity(self):
        self.data["prompts"].append({"id": "PROMPT-B", "template": "T1", "duration": None, "shot_id": None, "text": "生成[角色名称]参考图。"})
        results = qc.check_project(self.data)
        self.assertEqual([r.get("prompt_id") for r in results[1:]], ["PROMPT-A", "PROMPT-B"])
        self.assertFalse(results[1]["errors"])
        self.assertTrue(any("占位符" in e for e in results[2]["errors"]))

    def test_prompt_timestamps_must_match_structured_segments(self):
        self.data["shots"][0]["segments"][0]["end"] = 4.0
        results = qc.check_project(self.data)
        self.assertTrue(any("shot.segments" in e for e in results[1]["errors"]))

    def test_prompt_dialogue_must_match_words_and_order(self):
        self.data["prompts"][0]["text"] = dynamic_text().replace("我看见了。", "我知道了。")
        results = qc.check_project(self.data)
        self.assertTrue(any("台词文字或顺序" in e for e in results[1]["errors"]))

    def test_prompt_dialogue_can_adjust_punctuation(self):
        self.data["prompts"][0]["text"] = dynamic_text().replace("我看见了。", "我看见了！")
        self.assertFalse(qc.check_project(self.data)[1]["errors"])

    def test_cli_json_output_reports_prompt_errors_and_exit_status(self):
        self.data["prompts"][0]["text"] = dynamic_text().replace("别动。", "别跑。")
        fake_module = sys.modules["project_data"]
        fake_module.load_project = lambda path: deepcopy(self.data)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            status = qc.main(["project.json", "--format", "json"])
        output = json.loads(buffer.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(output["ok"])
        self.assertEqual(output["results"][1]["prompt_id"], "PROMPT-A")

    def test_bad_shape_skips_prompt_inspection(self):
        fake_module = sys.modules["project_data"]
        fake_module.validate_shape = lambda data: ["$.prompts: 类型应为array"]
        fake_module.validate_project = lambda data, previous=None: (["$.prompts: 类型应为array"], [])
        self.data["prompts"] = {"not": "an array"}
        results = qc.check_project(self.data)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["errors"])


class CLIInputChecks(unittest.TestCase):
    def test_real_demo_passes_project_and_per_prompt_checks(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            status = qc.main([str(ROOT / "examples" / "demo" / "project.json"), "--format", "json"])
        output = json.loads(buffer.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(len([r for r in output["results"] if r.get("prompt_id")]), 5)

    def test_stdin_project_parser_rejects_duplicate_keys_and_nonfinite_values(self):
        for text in ['{"project": {}, "project": {}}', '{"duration": NaN}']:
            with self.subTest(text=text):
                buffer = io.StringIO()
                with patch("sys.stdin", io.StringIO(text)), redirect_stdout(buffer):
                    status = qc.main(["--project", "--format", "json"])
                self.assertEqual(status, 1)
                self.assertFalse(json.loads(buffer.getvalue())["ok"])

    def test_invalid_project_shape_reports_fields_without_crashing(self):
        data = {"prompts": [{"text": "生成角色图", "shot_id": []}]}
        buffer = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(data))), redirect_stdout(buffer):
            status = qc.main(["--project", "--format", "json"])
        output = json.loads(buffer.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(len(output["results"]), 1)
        self.assertTrue(any("$." in error for error in output["results"][0]["errors"]))

    def test_empty_directory_and_management_only_document_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (Path(directory), Path(directory) / "notes.md"):
                if path.suffix:
                    path.write_text("# 管理数据\n```json\n{}\n```", encoding="utf-8")
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    status = qc.main([str(path), "--format", "json"])
                output = json.loads(buffer.getvalue())
                self.assertEqual(status, 1)
                self.assertFalse(output["ok"])
                self.assertEqual(output["checked"], 0)

    def test_unreadable_input_returns_machine_readable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                status = qc.main([str(Path(directory) / "missing.txt"), "--format", "json"])
            self.assertEqual(status, 1)
            self.assertTrue(json.loads(buffer.getvalue())["results"][0]["errors"])


if __name__ == "__main__":
    unittest.main()
