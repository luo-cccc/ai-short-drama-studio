"""Cross-module review regressions for visual conversion and sound-reference export."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from scripts.project_data import load_project, snapshot_dependencies
from scripts.qc_check import _visible_character_clauses, check
from scripts.render_project import build_wan_visual_prompt, export_project, render_documents


ROOT = Path(__file__).resolve().parents[1]


class ReviewOutputTests(unittest.TestCase):
    def test_visual_conversion_preserves_timestamp_and_action_before_dialogue(self):
        text = '生成一段5秒短片。\n镜头1（0.0-5.0s）：中近景，晚晴握紧铜钥匙说：“别动。”\n--ar 9:16'
        visual = build_wan_visual_prompt(text)
        self.assertIn('镜头1（0.0-5.0s）：', visual)
        self.assertIn('晚晴握紧铜钥匙', visual)
        self.assertNotIn('别动', visual)
        self.assertIn('嘴唇自然开合', visual)

    def test_hand_only_dialogue_does_not_add_a_visible_mouth(self):
        text = ('生成一段5秒短片。\n角色晚晴：窄脸，灰蓝长衫。\n'
                '镜头1（0.0-5.0s）：纯手部近景，手掌托住钥匙。\n'
                '她以清亮女中音说：“你看我的脸。”\n--ar 9:16')
        visual = build_wan_visual_prompt(text)
        self.assertIn('手掌托住钥匙', visual)
        self.assertNotIn('嘴唇', visual)
        self.assertNotIn('窄脸', visual)
        self.assertNotIn('你看我的脸', visual)

    def test_multiline_spoken_content_does_not_leak_into_visual_fallback(self):
        for dialogue in ['说：“钥匙\n还在这里。”', '说：\n“钥匙还在这里。”']:
            with self.subTest(dialogue=dialogue):
                text = '镜头1（0.0-5.0s）：中近景，晚晴托住钥匙，' + dialogue + '\n--ar 9:16'
                visual = build_wan_visual_prompt(text)
                self.assertIn('镜头1（0.0-5.0s）：', visual)
                self.assertIn('托住钥匙', visual)
                self.assertNotIn('还在这里', visual)
                self.assertNotIn('“', visual)
                self.assertNotIn('”', visual)

    def test_offscreen_continuation_does_not_delete_camera_header_or_action(self):
        text = '镜头1（0.0-5.0s）：掌心特写，晚晴托住钥匙，她的声音在画外继续。\n--ar 9:16'
        visual = build_wan_visual_prompt(text)
        self.assertIn('镜头1（0.0-5.0s）：', visual)
        self.assertIn('晚晴托住钥匙', visual)
        self.assertNotIn('声音在画外继续', visual)

    def test_negated_face_does_not_force_a_mouth_into_a_hand_shot(self):
        text = '镜头1（0.0-5.0s）：只有手部特写，不露面部，晚晴在画外说：“等一下。”\n--ar 9:16'
        visual = build_wan_visual_prompt(text)
        self.assertIn('只有手部特写', visual)
        self.assertNotIn('嘴唇', visual)

    def test_visibility_is_scoped_to_each_physical_camera_shot(self):
        text = ('镜头1（0.0-2.0s）：人物面部近景，晚晴说：“别动。”\n'
                '镜头2（2.0-5.0s）：纯手部特写，手托钥匙，她说：“还在这里。”\n--ar 9:16')
        visual = build_wan_visual_prompt(text)
        self.assertIn('嘴唇自然开合', visual.split('镜头2')[0])
        self.assertNotIn('嘴唇', visual.split('镜头2')[1])
        self.assertIn('手托钥匙', visual)

    def test_audio_slot_removal_preserves_role_identity_prefix(self):
        text = ('角色晚晴：声音身份参考@素材4，青年女性，灰蓝长衫。\n'
                '镜头1（0.0-5.0s）：中近景，人物站立。\n--ar 9:16')
        visual = build_wan_visual_prompt(text, ['@素材4'])
        self.assertIn('角色晚晴：青年女性', visual)
        self.assertNotIn('@素材4', visual)

    def test_encoding_failure_does_not_change_existing_export_or_create_new_output(self):
        data = load_project(ROOT / 'examples/demo/project.json')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'existing'
            export_project(data, output)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            prompt = data['prompts'][-1]
            prompt['text'] = prompt['text'].replace('场景旧院门：', '场景旧院门：\ud800')
            prompt['revision'] += 1
            data = snapshot_dependencies(data)
            with self.assertRaises(UnicodeEncodeError):
                export_project(data, output)
            self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})
            fresh = Path(temporary) / 'fresh'
            with self.assertRaises(UnicodeEncodeError):
                export_project(data, fresh)
            self.assertFalse(fresh.exists())

    def test_static_holds_are_review_warnings_not_required_new_actions(self):
        text = '生成三行三列故事板。\n' + '\n'.join(
            f'Shot #{i}（{i / 2:.1f}秒·物理镜头1）：人物在原构图静止保持。' for i in range(1, 10)
        ) + '\n--ar 9:16'
        errors, warnings = check(text, mode='static', template='T6B')
        self.assertFalse(errors)
        self.assertTrue(any('合法静止保持' in warning for warning in warnings))

    def test_local_or_offscreen_character_does_not_require_invisible_face(self):
        clauses = [('窄脸', ['窄脸']), ('平直眉', ['平直眉']), ('灰蓝袖口', ['灰蓝袖口'])]
        local = '角色晚晴：灰蓝袖口。\n镜头1（0.0-5.0s）：纯手部特写，五指托住钥匙。'
        self.assertEqual([clauses[-1]], _visible_character_clauses(clauses, local, '角色晚晴：灰蓝袖口。'))
        self.assertEqual([], _visible_character_clauses(clauses, local, '角色晚晴：仅画外发声，不出镜。'))

    def test_reference_board_is_not_automatically_a_pixel_frame(self):
        documents = render_documents(load_project(ROOT / 'examples/demo/project.json'))
        shot = documents['SHOT-001_分镜.md']
        self.assertIn('T5空间九视角仅作机位参考', shot)
        self.assertIn('T6B线稿用于结构参考', shot)
        self.assertIn('参考素材资产', documents['project.md'])

    def test_wan_visual_prompt_cleans_complex_vocal_prefixes_and_punctuation(self):
        text = (
            '生成一段单镜头5秒的悬疑短片，同步生成环境音，音效，配音与背景音乐，音画口型同步。画面纯净，无字幕。\n'
            '镜头1（0.0-5.0s）：中近景，晚晴站在门前，以清亮女中音、匀速而克制地说：“门锁换过了。”随后她压低声音缓缓说道：“有人来过。”\n'
            '--ar 9:16'
        )
        visual = build_wan_visual_prompt(text)
        self.assertNotIn('清亮女中音', visual)
        self.assertNotIn('压低声音', visual)
        self.assertNotIn('门锁换过了', visual)
        self.assertNotIn('有人来过', visual)
        self.assertIn('嘴唇自然开合完成说话动作。', visual)


if __name__ == '__main__':
    unittest.main()
