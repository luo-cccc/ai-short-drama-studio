"""项目数据契约的可观察形状约束；无需第三方 JSON Schema 运行库。"""
import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_data import validate_shape


class ProjectSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = json.loads((ROOT / "examples/demo/project.json").read_text(encoding="utf-8"))

    def assert_shape_error(self, change, field):
        data = copy.deepcopy(self.demo)
        change(data)
        errors = validate_shape(data)
        self.assertTrue(any(field in error for error in errors), errors)

    def test_complete_demo_matches_contract(self):
        self.assertEqual([], validate_shape(self.demo))

    def test_required_voice_cannot_be_omitted(self):
        self.assert_shape_error(lambda data: data["characters"][0].pop("voice"), "voice")

    def test_unknown_fields_are_rejected(self):
        self.assert_shape_error(lambda data: data["project"].update({"debug": True}), "debug")

    def test_character_id_cannot_use_scene_namespace(self):
        self.assert_shape_error(lambda data: data["characters"][0].update(id="SCENE-WANQING"), "characters[0].id")

    def test_boolean_is_not_a_revision_integer(self):
        self.assert_shape_error(lambda data: data["characters"][0].update(revision=True), "characters[0].revision")

    def test_whitespace_is_not_an_asset_name(self):
        self.assert_shape_error(lambda data: data["characters"][0].update(name="  \t"), "characters[0].name")

    def test_time_precision_is_at_most_one_decimal(self):
        self.assert_shape_error(lambda data: data["shots"][0].update(duration=5.05), "shots[0].duration")

    def test_static_prompt_duration_can_be_null(self):
        data = copy.deepcopy(self.demo)
        data["prompts"][0]["duration"] = None
        self.assertEqual([], validate_shape(data))

    def test_nonexistent_design_role_is_rejected(self):
        self.assert_shape_error(lambda data: data["shots"][0]["design"][0].update(role="invented"), "shots[0].design[0].role")

    def test_arbitrary_reference_slots_are_rejected(self):
        self.assert_shape_error(lambda data: data["prompts"][0]["reference_bindings"][0].update(slot="image zero"), "reference_bindings[0].slot")

    def test_dependencies_require_sha256_fingerprint(self):
        self.assert_shape_error(lambda data: data["shots"][0].update(depends_on=[{"id": "CHAR-WANQING", "revision": 1, "fingerprint": "not-a-hash"}]), "fingerprint")

    def test_non_array_entities_are_rejected(self):
        self.assert_shape_error(lambda data: data.update(characters={}), "characters")

    def test_shot_function_is_required(self):
        self.assert_shape_error(lambda data: data["shots"][0].pop("function"), "function")

    def test_incoming_transition_cannot_be_blank(self):
        self.assert_shape_error(lambda data: data["shots"][0]["transitions"].update(incoming="  "), "incoming")

    def test_review_status_uses_known_states(self):
        self.assert_shape_error(lambda data: data["shots"][0]["review"].update(status="done"), "status")

    def test_design_id_uses_9b_namespace(self):
        self.assert_shape_error(lambda data: data["shots"][0]["review"].update(design_id="SHOT-001"), "design_id")

    def test_notes_may_be_empty(self):
        data = copy.deepcopy(self.demo)
        data["shots"][0]["notes"] = ""
        self.assertEqual([], validate_shape(data))

    def test_optional_source_ref_on_beats_and_dialogues(self):
        data = copy.deepcopy(self.demo)
        data["beats"][0]["source_ref"] = "E01-S01-A01"
        data["beats"][1]["source_ref"] = None
        data["dialogues"][0]["source_ref"] = "E01-S01-D01"
        data["dialogues"][1]["source_ref"] = None
        self.assertEqual([], validate_shape(data))
        self.assert_shape_error(lambda d: d["beats"][0].update(source_ref="   "), "beats[0].source_ref")
        self.assert_shape_error(lambda d: d["dialogues"][0].update(source_ref=123), "dialogues[0].source_ref")


if __name__ == "__main__":
    unittest.main()
