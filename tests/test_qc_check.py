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

    def test_spoken_management_words_are_allowed_only_in_dynamic_shots(self):
        for quote in ['"你就是按模板做事的人。"', '“请把首帧和尾帧发给我。”']:
            with self.subTest(quote=quote):
                source = dynamic_text().replace('"别动。"', quote)
                self.assertFalse(qc.check(source, duration=10)[0])
        for source, mode in [
            ('生成角色图，注明“模板”与“首帧”。', "static"),
            ('生成角色图，注明“这是\n模板说明。”', "static"),
            ('“模板”用于本片。\n' + dynamic_text(), "dynamic"),
            ('“这是\n模板说明。”\n' + dynamic_text(), "dynamic"),
            (dynamic_text().replace("--ar 16:9", '尾部说明使用“模板”。\n--ar 16:9'), "dynamic"),
            (dynamic_text().replace("--ar 16:9", '尾部说明使用“这是\n模板说明。”\n--ar 16:9'), "dynamic"),
            (dynamic_text().replace("镜头平移，", "首帧保持清楚，镜头平移，"), "dynamic"),
        ]:
            with self.subTest(mode=mode, source=source):
                errors, _ = qc.check(source, mode=mode, duration=10)
                self.assertTrue(any("机制/管理标签" in error for error in errors), errors)

    def test_spoken_continuation_lines_keep_management_words(self):
        for cue in ["林舟低声说", "晚晴短句收尾", "轻声低语", "OS", "NAR"]:
            with self.subTest(cue=cue):
                source = dynamic_text().replace('低声匀速说："别动。"', '\n' + cue + '：“你就是按模板做事的人。”')
                self.assertFalse(qc.check(source, duration=10)[0])
        source = dynamic_text().replace('低声匀速说："别动。"', '\n说明：“模板”位于这里。')
        self.assertTrue(any("机制/管理标签" in error for error in qc.check(source, duration=10)[0]))

    def test_dialogue_exemption_preserves_punctuation_placeholders_and_slots(self):
        for utterance, expected in [
            ("模板、首帧。", "禁用标点"),
            ("模板[角色名称]。", "占位符残留"),
            ("模板@素材9。", "没有独立参考声明"),
        ]:
            with self.subTest(utterance=utterance):
                errors, _ = qc.check(dynamic_text().replace("别动。", utterance), duration=10)
                self.assertTrue(any(expected in error for error in errors), errors)

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
        source = "@图片1 参考场景空间布局、色彩光影与画面风格。禁止继承构图、景别。\n生成彩色故事版。\n--ar 9:16"
        errors, _ = qc.check(source, mode="static", template="T6")
        self.assertFalse(errors)

    def test_storyboard_nine_grid_completeness_and_uniqueness_check(self):
        cells = [f"Shot #{i}（节点{i}·物理镜头1）：第{i}格差异化关键帧描述。" for i in range(1, 10)]
        valid_board = "生成三行三列关键帧故事板。\n" + "\n".join(cells) + "\n--ar 9:16"
        self.assertFalse(qc.check(valid_board, mode="static", template="T6B")[0])

        incomplete = "生成三行三列关键帧故事板。\n" + "\n".join(cells[:6]) + "\n--ar 9:16"
        errors, _ = qc.check(incomplete, mode="static", template="T6B")
        self.assertTrue(any("Shot #1至Shot #9" in e for e in errors), errors)

        duplicated = list(cells)
        duplicated[4] = "Shot #5（节点5·物理镜头1）：第1格差异化关键帧描述。"
        dup_board = "生成三行三列关键帧故事板。\n" + "\n".join(duplicated) + "\n--ar 9:16"
        errors, warnings = qc.check(dup_board, mode="static", template="T6")
        self.assertFalse(errors, errors)
        self.assertTrue(any("合法静止保持" in item for item in warnings), warnings)

        backwards = list(cells)
        backwards[2] = "Shot #3（2.5秒·物理镜头1）：第3格描述。"
        backwards[3] = "Shot #4（1.8秒·物理镜头1）：第4格描述。"
        backwards_board = "生成三行三列关键帧故事板。\n" + "\n".join(backwards) + "\n--ar 9:16"
        errors, _ = qc.check(backwards_board, mode="static", template="T6B")
        self.assertTrue(any("时间节点倒退" in e for e in errors), errors)

    def test_dynamic_sub_interval_inversion_and_out_of_bounds_are_reported(self):
        inverted = dynamic_text().replace(
            '镜头1（0.0-5.0s）：镜头平移，林舟停在木门旁，低声匀速说："别动。"',
            '镜头1（0.0-5.0s）：3.0–1.5秒林舟停在木门旁，低声匀速说："别动。"',
        )
        errors, _ = qc.check(inverted, duration=10, template="T9")
        self.assertTrue(any("阶段时间区间倒置" in e for e in errors), errors)

        out_of_bounds = dynamic_text().replace(
            '镜头1（0.0-5.0s）：镜头平移，林舟停在木门旁，低声匀速说："别动。"',
            '镜头1（0.0-5.0s）：5.5–7.0秒林舟停在木门旁，低声匀速说："别动。"',
        )
        errors, _ = qc.check(out_of_bounds, duration=10, template="T9")
        self.assertTrue(any("超出有效时间范围" in e for e in errors), errors)

    def test_short_shot_action_density_overload_emits_warning(self):
        overloaded = dynamic_text().replace(
            '镜头1（0.0-5.0s）：镜头平移，林舟停在木门旁，低声匀速说："别动。"',
            '镜头1（0.0-5.0s）：0.0–0.5秒林舟转头，0.5–1.2秒抬手，1.2–2.0秒探入木缝，2.0–3.0秒抽出钥匙，3.0–4.5秒翻掌并低声匀速说："别动。"',
        )
        errors, warnings = qc.check(overloaded, duration=10, template="T9")
        self.assertFalse(errors)
        self.assertTrue(any("单镜动作密度过高" in w for w in warnings), warnings)

    def test_static_scene_reference_conflict_checks_actual_overlap(self):
        disjoint = "@图片1 参考场景空间布局与色彩光影。禁止继承画面风格。\n生成彩色故事版。\n--ar 16:9"
        self.assertFalse(qc.check(disjoint, mode="static", template="T6")[0])
        overlapping = "@图片1 参考场景空间布局与色彩光影。禁止继承色彩。\n生成彩色故事版。\n--ar 16:9"
        errors, _ = qc.check(overlapping, mode="static", template="T6")
        self.assertTrue(any("静态场景参考的继承项与禁止项冲突" in e for e in errors), errors)

    def test_dynamic_scene_reference_allows_inline_exclusion_clause(self):
        source = "@素材1 参考场景旧院门除色彩、光影外的空间布局。禁止继承画面风格、光影、色彩。\n" + dynamic_text()
        errors, _ = qc.check(source, duration=10, template="T9")
        self.assertFalse(errors)

    def test_dynamic_scene_reference_keeps_its_inheritance_restrictions(self):
        source = "@素材1 参考场景空间布局。禁止继承构图、景别。\n" + dynamic_text()
        errors, _ = qc.check(source, mode="dynamic", duration=10, template="T9")
        self.assertTrue(any("动态场景/故事板参考缺少" in error for error in errors))

    def test_dynamic_scene_reference_requires_complete_exclusions_without_borrowing(self):
        for declaration in [
            "@素材1 参考场景空间布局。",
            "@素材1 参考场景空间布局。\n禁止继承构图、景别。",
            "@素材1 参考故事板空间站位。\n\n禁止继承画面风格、光影。",
            "@素材1 参考故事分镜图空间站位。\n@素材2 参考角色外观。禁止继承画面风格、光影、色彩。",
            "@素材1 参考调度图空间站位。\n生成影片。\n禁止继承画面风格、光影、色彩。",
        ]:
            with self.subTest(declaration=declaration):
                errors, _ = qc.check(declaration + "\n" + dynamic_text(), duration=10, template="T9")
                self.assertTrue(any("@素材1动态场景/故事板参考缺少" in error for error in errors), errors)

    def test_dynamic_scene_reference_accepts_inline_and_separate_protocol_lines(self):
        for declaration in [
            "@素材1 参考场景空间布局。禁止继承画面风格、光影、色彩。",
            "  @素材1\t参考 场景空间布局。\n\n  禁止继承 画面风格 ， 光影 ， 色彩 。  ",
            "@素材1 参考故事板空间站位。\n禁止继承画面风格。\n\n禁止继承光影、色彩。",
            "@素材1 参考调度图空间站位，只取造型结构，不取颜色与光影。\n禁止继承画面风格、光影、色彩。",
        ]:
            with self.subTest(declaration=declaration):
                errors, _ = qc.check(declaration + "\n" + dynamic_text(), duration=10, template="T9")
                self.assertFalse(errors)

    def test_dynamic_scene_reference_rejects_positive_inheritance_even_with_exclusions(self):
        for reference in [
            "场景画面风格、光影、色彩。",
            "场景空间布局。并继承光影与色彩。",
            "故事板空间站位。\n继续沿用画面风格。",
            "调度图空间站位。禁止继承画面风格、光影、色彩，但保留原图光影。",
        ]:
            with self.subTest(reference=reference):
                source = "@素材1 参考" + reference + "\n禁止继承画面风格、光影、色彩。\n" + dynamic_text()
                errors, _ = qc.check(source, duration=10, template="T9")
                self.assertTrue(any("不能正向继承" in error for error in errors), errors)

    def test_dynamic_character_and_prop_references_are_not_scene_references(self):
        source = "\n".join([
            "@素材1 参考角色林舟的外观、服饰与固有色彩。禁止继承场景背景、光影。",
            "@素材2 参考道具铜钥匙的固有配色、材质与画面风格。禁止继承场景背景、光影。",
            "@素材3 参考人物脸部与服装。禁止继承场景色彩。",
            dynamic_text(),
        ])
        self.assertFalse(qc.check(source, duration=10, template="T9")[0])

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


class CompleteProjectQCRegressionTests(unittest.TestCase):
    def synchronized_dialogue(self, utterance, continuation=False):
        from scripts.project_data import load_project, snapshot_dependencies

        data = load_project(ROOT / "examples" / "demo" / "project.json")
        line = data["dialogues"][0]
        old, line["text"] = line["text"], utterance
        line["revision"] += 1
        for shot in data["shots"]:
            for segment in shot["segments"]:
                for delivery in segment["lines"]:
                    if delivery["dialogue_id"] == line["id"]:
                        delivery["text"] = line["text"]
                        shot["revision"] += 1
        for prompt in data["prompts"]:
            if prompt["template"] in {"T7", "T8", "T9"} and old in prompt["text"]:
                prompt["text"] = prompt["text"].replace(old, line["text"])
                if continuation:
                    prompt["text"] = prompt["text"].replace(
                        "清亮女中音，匀速，短句收尾：", "\n晚晴低声说："
                    )
                prompt["revision"] += 1
        return snapshot_dependencies(data)

    def test_synchronized_spoken_management_words_pass_qc_and_export(self):
        from scripts.render_project import export_project

        for continuation in [False, True]:
            with self.subTest(continuation=continuation):
                utterance = "你就是按模板做事的人。"
                data = self.synchronized_dialogue(utterance, continuation)
                errors = [error for result in qc.check_project(data) for error in result["errors"]]
                self.assertFalse(errors)
                with tempfile.TemporaryDirectory() as directory:
                    paths, _ = export_project(data, directory)
                    self.assertTrue(any(utterance in path.read_text(encoding="utf-8") for path in paths))

    def test_multiline_chinese_dialogue_passes_complete_project_qc_and_export(self):
        from scripts.project_data import validate_project
        from scripts.render_project import export_project

        for continuation in [False, True]:
            with self.subTest(continuation=continuation):
                utterance = "你就是按\n模板做事的人。"
                data = self.synchronized_dialogue(utterance, continuation)
                self.assertFalse(validate_project(data)[0])
                self.assertFalse([error for result in qc.check_project(data) for error in result["errors"]])
                with tempfile.TemporaryDirectory() as directory:
                    paths, _ = export_project(data, directory)
                    self.assertTrue(any(utterance in path.read_text(encoding="utf-8") for path in paths))

    def test_invalid_scene_reference_blocks_complete_project_export(self):
        from scripts.project_data import load_project, snapshot_dependencies
        from scripts.render_project import export_project

        for declaration in [
            "@素材2 参考场景旧院门的空间布局。",
            "@素材2 参考场景旧院门的空间布局。\n禁止继承构图、景别。",
            "@素材2 参考场景旧院门的画面风格、光影、色彩。\n禁止继承画面风格、光影、色彩。",
        ]:
            with self.subTest(declaration=declaration):
                data = load_project(ROOT / "examples" / "demo" / "project.json")
                prompt = next(prompt for prompt in data["prompts"] if prompt["id"] == "PROMPT-VIDEO-001")
                rows = prompt["text"].splitlines()
                rows[1] = declaration
                prompt["text"] = "\n".join(rows)
                prompt["revision"] += 1
                data = snapshot_dependencies(data)
                errors = [error for result in qc.check_project(data) for error in result["errors"]]
                self.assertTrue(any("动态场景/故事板参考" in error for error in errors), errors)
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "delivery"
                    with self.assertRaisesRegex(ValueError, "动态场景/故事板参考"):
                        export_project(data, output)
                    self.assertFalse(output.exists())

    def test_character_and_prop_dna_drift_and_scene_lighting_flip_warnings(self):
        from scripts.project_data import load_project, snapshot_dependencies

        data = load_project(ROOT / "examples" / "demo" / "project.json")
        # 1. 制造角色与道具外貌 DNA 漂移
        drifted = deepcopy(data)
        p2 = next(p for p in drifted["prompts"] if p["id"] == "PROMPT-VIDEO-002")
        p2["text"] = p2["text"].replace(
            "年轻东亚女性，窄脸，平直眉，深棕瞳孔，黑发低束，清瘦身形，灰蓝长衫，黑布鞋",
            "金发碧眼少女，波浪长发，红色晚礼服，高跟鞋",
        ).replace(
            "扁平铜质，环形匙柄，缺角齿口，表面细小暗斑",
            "方形木牌，光滑表面",
        )
        p2["revision"] += 1
        drifted = snapshot_dependencies(drifted)
        warnings = [w for r in qc.check_project(drifted) for w in r["warnings"]]
        self.assertTrue(any("角色晚晴（CHAR-WANQING）" in w and "外貌一致性" in w for w in warnings), warnings)
        self.assertTrue(any("道具铜钥匙（PROP-KEY）" in w and "跨镜一致性" in w for w in warnings), warnings)

        # 2. 制造同场景跨镜光影冷暖突变
        flipped = deepcopy(data)
        for item in flipped["shots"][1]["design"]:
            if item["role"] == "lighting":
                item["decision"] = "夕阳暖金斜射光与暖黄火光基调。"
        p2_flip = next(p for p in flipped["prompts"] if p["id"] == "PROMPT-VIDEO-002")
        p2_flip["text"] = p2_flip["text"].replace("冷白柔和", "暖金柔和").replace("灰蓝低饱和", "暖黄高饱和")
        flipped["shots"][1]["revision"] += 1
        p2_flip["revision"] += 1
        flipped = snapshot_dependencies(flipped)
        proj_warnings = qc.check_project(flipped)[0]["warnings"]
        self.assertTrue(any("光影冷暖基调发生突变（冷调→暖调）" in w for w in proj_warnings), proj_warnings)

    def test_storyboard_cross_field_segment_and_duration_checks(self):
        from scripts.project_data import load_project, snapshot_dependencies

        data = load_project(ROOT / "examples" / "demo" / "project.json")
        board = next(p for p in data["prompts"] if p["id"] == "PROMPT-BOARD-001")
        board["text"] = board["text"].replace(
            "Shot #9（5.0秒切出末态·物理镜头1）",
            "Shot #9（6.5秒切出末态·物理镜头2）",
        )
        board["revision"] += 1
        rebuilt = snapshot_dependencies(data)
        board_res = next(r for r in qc.check_project(rebuilt) if r.get("prompt_id") == "PROMPT-BOARD-001")
        self.assertTrue(any("超出所属分镜duration" in e for e in board_res["errors"]), board_res["errors"])
        self.assertTrue(any("不存在的物理镜头2" in e for e in board_res["errors"]), board_res["errors"])

    def test_cross_outfit_face_dna_lock_and_costume_variant_exemption(self):
        from scripts.project_data import load_project, snapshot_dependencies

        data = load_project(ROOT / "examples" / "demo" / "project.json")
        # 1. 保留全套旧衣服但丢失五官骨相（换脸但没换衣）-> 必须触发面部五官骨相缺失警告
        face_lost = deepcopy(data)
        p2 = next(p for p in face_lost["prompts"] if p["id"] == "PROMPT-VIDEO-002")
        p2["text"] = p2["text"].replace(
            "窄脸，平直眉，深棕瞳孔，黑发低束，清瘦身形，灰蓝长衫，黑布鞋",
            "圆润娃娃脸，弯月细眉，浅蓝瞳孔，黑发低束，清瘦身形，灰蓝长衫，黑布鞋",
        )
        p2["revision"] += 1
        face_lost = snapshot_dependencies(face_lost)
        p2_warns = next(r for r in qc.check_project(face_lost) if r.get("prompt_id") == "PROMPT-VIDEO-002")["warnings"]
        self.assertTrue(any("核心面部五官/骨相特征缺失或偏离" in w for w in p2_warns), p2_warns)

        # 2. 跨服装/跨状态变体：锁死全部面部五官骨相（窄脸、平直眉、深棕瞳孔），但换穿新衣、新发式与新鞋 -> 不误报外貌偏离
        costume_variant = deepcopy(data)
        p2_var = next(p for p in costume_variant["prompts"] if p["id"] == "PROMPT-VIDEO-002")
        p2_var["text"] = p2_var["text"].replace(
            "@素材1 参考角色晚晴的外观，服饰，固有配色与画面风格。禁止继承背景，叙事光影，整体调色，动作，表情。",
            "@素材1 参考角色晚晴面部母图的五官骨相与脸型比例。禁止继承原图服装款式，旧状态，背景，叙事光影，整体调色，动作，表情。",
        ).replace(
            "窄脸，平直眉，深棕瞳孔，黑发低束，清瘦身形，灰蓝长衫，黑布鞋",
            "窄脸，平直眉，深棕瞳孔，高盘发髻，清瘦身形，换穿绯红喜服，金丝绣花鞋",
        )
        p2_var["revision"] += 1
        costume_variant = snapshot_dependencies(costume_variant)
        p2_var_warns = next(r for r in qc.check_project(costume_variant) if r.get("prompt_id") == "PROMPT-VIDEO-002")["warnings"]
        self.assertFalse(any("CHAR-WANQING" in w and "外貌一致性" in w for w in p2_var_warns), p2_var_warns)

        # 3. 变体 T1 未绑定 @图片1 纯文本生成 -> 警告跨服装换脸风险
        unanchored_t1 = deepcopy(data)
        unanchored_t1["prompts"].append({
            "id": "PROMPT-CHAR-WANQING-WET",
            "revision": 1,
            "template": "T1",
            "shot_id": None,
            "duration": None,
            "asset_ids": ["CHAR-WANQING"],
            "reference_bindings": [],
            "text": (
                "生成一张角色完整视觉设定参考图，所有视图展示同一角色。\n"
                "晚晴，年轻东亚女性，窄脸，平直眉，深棕瞳孔，清瘦身形，湿身状态，换穿夜行黑衣与软底短靴。\n"
                "--ar 16:9"
            ),
            "depends_on": [],
        })
        unanchored_t1 = snapshot_dependencies(unanchored_t1)
        t1_warns = next(r for r in qc.check_project(unanchored_t1) if r.get("prompt_id") == "PROMPT-CHAR-WANQING-WET")["warnings"]
        self.assertTrue(any("未绑定基底角色参考图" in w for w in t1_warns), t1_warns)

    def test_reference_attribute_contradiction_and_storyboard_face_pollution_and_voice_timbre(self):
        from scripts.project_data import load_project, snapshot_dependencies

        # 1. 角色换装参考声明同时正向继承与禁止继承“服装” -> 报错
        contradictory = (
            "@图片1 参考目标角色晚晴的五官骨相与服装结构。禁止继承服装结构、背景、动作、表情。\n"
            "生成一张角色完整视觉设定参考图。\n--ar 16:9"
        )
        errors, _ = qc.check(contradictory, mode="static", template="T1")
        self.assertTrue(any("继承项与禁止项冲突" in e and "服装" in e for e in errors), errors)

        # 2. T6C 或动态提示词从故事板/结构切片正向继承“五官面容” -> 警告二手切片导致换脸
        slice_face = (
            "@图片1 参考关键帧结构切片的主体站位、人物五官面容与取景构图。禁止继承画面风格、光影、色彩。\n"
            "生成一张单画面满幅的影视关键帧参考图。\n--ar 9:16"
        )
        _, warns = qc.check(slice_face, mode="static", template="T6C")
        self.assertTrue(any("故事板/结构切片参考不宜正向继承人物五官面容" in w for w in warns), warns)

        # 3. 角色发声镜头篡改或丢失 characters.voice 声线特征 -> 警告跨镜声线偏离
        data = load_project(ROOT / "examples" / "demo" / "project.json")
        p1 = next(p for p in data["prompts"] if p["id"] == "PROMPT-VIDEO-001")
        p1["text"] = p1["text"].replace("清亮女中音", "粗粝苍老声线")
        p1["revision"] += 1
        rebuilt = snapshot_dependencies(data)
        p1_warns = next(r for r in qc.check_project(rebuilt) if r.get("prompt_id") == "PROMPT-VIDEO-001")["warnings"]
        self.assertTrue(any("跨镜声线一致性" in w for w in p1_warns), p1_warns)

        # 4. 全局角色设定缺少面部五官骨相（仅写衣服身材）-> 项目级警告跨状态易换脸
        no_face_proj = load_project(ROOT / "examples" / "demo" / "project.json")
        no_face_proj["characters"][0]["description"] = "年轻女性，身形高挑，灰蓝长衫，黑布鞋。"
        no_face_proj["characters"][0]["revision"] += 1
        no_face_proj = snapshot_dependencies(no_face_proj)
        proj_warns = qc.check_project(no_face_proj)[0]["warnings"]
        self.assertTrue(any("缺少足够的不可变面部五官/骨相特征" in w for w in proj_warns), proj_warns)

        # 5. 多切镜（镜头1纯背影 + 镜头2面部近景）必须保留面部五官DNA核对，不能因镜头1含“纯背影”而漏检面部
        clauses = [("窄脸", ["窄脸"]), ("平直眉", ["平直眉"]), ("灰蓝长衫", ["灰蓝长衫"])]
        multi_seg = (
            "角色晚晴：窄脸，平直眉，灰蓝长衫。\n"
            "镜头1（0.0-2.5s）：中景，纯背影，晚晴走向院门。\n"
            "镜头2（2.5-5.0s）：面部近景，晚晴转头看锁。"
        )
        self.assertEqual(clauses, qc._visible_character_clauses(clauses, multi_seg, "角色晚晴：窄脸，平直眉，灰蓝长衫。"))

        # 6. 多人同框静态 T6C/T6 提示词：角色B不能借用角色A的外观描述蒙混通过DNA核对
        multi_char = load_project(ROOT / "examples" / "demo" / "project.json")
        multi_char["characters"].append({
            "id": "CHAR-SISTER",
            "revision": 1,
            "name": "晚霜",
            "description": "年轻东亚女性，窄脸，平直眉，深棕瞳孔，黑发低束，身形清瘦，灰蓝长衫，黑布鞋。",
            "voice": "清冷女中音，匀速。",
        })
        multi_char["beats"][0]["character_ids"].append("CHAR-SISTER")
        multi_char["shots"][0]["character_ids"].append("CHAR-SISTER")
        multi_char["prompts"].append({
            "id": "PROMPT-FRAME-001",
            "revision": 1,
            "template": "T6C",
            "shot_id": "SHOT-001",
            "duration": None,
            "asset_ids": ["CHAR-WANQING", "CHAR-SISTER", "SCENE-GATE"],
            "reference_bindings": [],
            "text": (
                "生成一张单画面满幅的影视关键帧参考图。\n"
                "角色晚晴：年轻东亚女性，窄脸，平直眉，深棕瞳孔，黑发低束，身形清瘦，灰蓝长衫，黑布鞋。\n"
                "角色晚霜：金发碧眼，波浪卷发，晚礼服。\n"
                "整体情绪为警觉。\n"
                "写实风格，柔和天光，平视中近景。\n"
                "两人站位清晰，衣袖贴合手腕，门框线条连贯。\n"
                "--ar 9:16"
            ),
            "depends_on": [],
        })
        multi_char["shots"][0]["static_prompt_ids"].append("PROMPT-FRAME-001")
        for pid in ("PROMPT-BOARD-001", "PROMPT-VIDEO-001"):
            pr = next(p for p in multi_char["prompts"] if p["id"] == pid)
            pr["asset_ids"].append("CHAR-SISTER")
        multi_char = snapshot_dependencies(multi_char)
        frame_warns = next(r for r in qc.check_project(multi_char) if r.get("prompt_id") == "PROMPT-FRAME-001")["warnings"]
        self.assertTrue(any("角色晚霜（CHAR-SISTER）" in w and "核心面部五官/骨相特征缺失" in w for w in frame_warns), frame_warns)


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

    def test_cli_source_and_shared_assets_flags(self):
        demo_path = ROOT / "examples" / "demo" / "project.json"
        preproduction_path = ROOT / "examples" / "demo" / "preproduction.md"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            status = qc.main([
                str(demo_path),
                "--source", str(preproduction_path),
                "--shared-assets", str(demo_path),
                "--format", "json",
            ])
        output = json.loads(buffer.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(output["ok"])


if __name__ == "__main__":
    unittest.main()
