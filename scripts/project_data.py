#!/usr/bin/env python3
"""Project data validation and explicit dependency snapshots (standard library only)."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "project.schema.json"
COLLECTIONS = ("characters", "scenes", "props", "beats", "dialogues", "shots", "prompts")
STATIC_TEMPLATES = {"T1", "T2", "T3", "T4", "T5", "T6", "T6B"}
DYNAMIC_TEMPLATES = {"T7", "T8", "T9"}
DESIGN_ROLES = ("director", "camera", "lighting", "action", "staging", "dialogue", "sound", "vfx")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 键：{key}")
        result[key] = value
    return result


def parse_project(text):
    return json.loads(text.lstrip("\ufeff"), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f"非有限数值：{value}")))


def load_project(path):
    return parse_project(Path(path).read_text(encoding="utf-8-sig"))


def normalize_dialogue(text):
    """Allow punctuation/spacing edits, while preserving every spoken character."""
    return "".join(char for char in unicodedata.normalize("NFC", text)
                   if not char.isspace() and not unicodedata.category(char).startswith("P"))


def entity_fingerprint(entity):
    content = {key: value for key, value in entity.items() if key != "depends_on"}
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_type(value, kind):
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: (isinstance(value, int) and not isinstance(value, bool))
                          or (isinstance(value, float) and math.isfinite(value)),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }[kind]()


def _shape_errors(value, schema, root, path="$"):
    """Validate exactly the JSON Schema vocabulary used in our bundled contract."""
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        yield from _shape_errors(value, target, root, path)
        return
    kinds = schema.get("type", [])
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if kinds and not any(_is_type(value, kind) for kind in kinds):
        yield f"{path}: 类型应为 {'/'.join(kinds)}"
        return
    if "const" in schema and value != schema["const"]:
        yield f"{path}: 必须为 {schema['const']!r}"
    if "enum" in schema and value not in schema["enum"]:
        yield f"{path}: 值不在允许枚举中"
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                yield f"{path}.{key}: 缺少必填字段"
        for key, child in value.items():
            if key in properties:
                yield from _shape_errors(child, properties[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                yield f"{path}.{key}: 未知字段"
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            yield f"{path}: 数组元素过少"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            yield f"{path}: 数组元素过多"
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                yield f"{path}: 数组存在重复项"
        for index, child in enumerate(value):
            if "items" in schema:
                yield from _shape_errors(child, schema["items"], root, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            yield f"{path}: 字符串过短"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            yield f"{path}: 字符串过长"
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            yield f"{path}: 不符合格式 {schema['pattern']}"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            yield f"{path}: 小于下限 {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            yield f"{path}: 超过上限 {schema['maximum']}"
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            yield f"{path}: 必须大于 {schema['exclusiveMinimum']}"
        if "multipleOf" in schema:
            try:
                if Decimal(str(value)) % Decimal(str(schema["multipleOf"])) != 0:
                    yield f"{path}: 必须是 {schema['multipleOf']} 的整数倍"
            except InvalidOperation:
                yield f"{path}: 非法数值"


def validate_shape(data):
    schema = load_project(SCHEMA_PATH)
    return list(_shape_errors(data, schema, schema))


def entity_index(data):
    entities = [data["project"]]
    for collection in COLLECTIONS:
        entities.extend(data[collection])
    return {entity["id"]: entity for entity in entities}


NON_SPEAKER_LABELS = {
    "出场人物", "人物", "角色", "可操作道具", "道具", "场景", "地点", "时间", "日夜", "内外",
    "音效", "音乐", "BGM", "环境音", "字幕", "花字", "画内文字", "备注", "说明", "注意",
    "提示", "总结", "结论", "建议", "问题", "证据", "判断", "未验证项", "主方向", "视觉形态",
    "叙事路线", "局部变化", "制作计划", "声音", "核心梗", "一句话卖点", "故事梗概",
}


def _parse_dialogue_clause(text, source_ref=None):
    match = re.match(
        r"^([\u4e00-\u9fffA-Za-z0-9_·]{1,20}?)(?:[（(]([^）)\n]{1,40})[）)])?[：:]\s*(.+)$",
        text.strip(),
    )
    if not match:
        return None
    speaker, modifier, utterance = match.groups()
    speaker = speaker.strip()
    modifier = (modifier or "").strip()
    utterance = utterance.strip()
    if not utterance or speaker in NON_SPEAKER_LABELS:
        return None
    if speaker in {"旁白", "NAR", "画外音", "叙述者"} or re.search(r"\bNAR\b|旁白|画外音", modifier, re.I):
        kind, speaker_name = "narration", None
    elif speaker.upper() == "OS" or re.search(r"\bOS\b|内心独白|独白|心声", modifier, re.I):
        kind = "os"
        speaker_name = modifier if speaker.upper() == "OS" and modifier else speaker
    else:
        kind, speaker_name = "dialogue", speaker
    return {
        "source_ref": source_ref,
        "speaker": speaker_name,
        "modifier": modifier or None,
        "kind": kind,
        "text": utterance,
    }


def parse_source_script(text, known_speakers=None):
    """Parse anchored handoff markdown or standard scene script into actions, dialogues, and mappings."""
    anchors, short_counts, short_map = {}, Counter(), {}
    actions, dialogues = [], []
    beat_shot_mappings, ref_line_mappings = [], []
    referenced_ids = set()
    speakers = set(known_speakers or ()) | {"旁白", "NAR", "画外音", "叙述者", "OS"}
    in_ignored_fence = False
    fence_marker = None
    saw_action_in_section = False

    for raw_line in text.lstrip("\ufeff").splitlines():
        trimmed = raw_line.strip()
        fence_match = re.match(r"^(`{3,}|~{3,})\s*([^\s]*)", trimmed)
        if fence_match:
            marker, lang = fence_match.group(1), fence_match.group(2).lower()
            if not in_ignored_fence and fence_marker is None:
                fence_marker = marker[0]
                in_ignored_fence = lang in {"json", "python", "powershell", "bash", "sh", "cmd", "yaml"}
            elif trimmed.startswith(fence_marker * 3):
                in_ignored_fence = False
                fence_marker = None
            continue
        if in_ignored_fence:
            continue

        for beat_id, shot_id in re.findall(r"\b(BEAT-[A-Za-z0-9_-]+)\s*(?:→|->)\s*(SHOT-[A-Za-z0-9_-]+)", raw_line):
            beat_shot_mappings.append((beat_id, shot_id))
        for ref_id, line_id in re.findall(r"\b([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s*(?:→|->)\s*(LINE-[A-Za-z0-9_-]+)", raw_line):
            if not ref_id.startswith(("BEAT-", "SHOT-", "CHAR-", "SCENE-", "PROP-", "PROMPT-", "PRJ-")):
                ref_line_mappings.append((ref_id, line_id))
        referenced_ids.update(
            re.findall(r"\b(?:PRJ|CHAR|SCENE|PROP|BEAT|LINE|SHOT|PROMPT)-[A-Za-z0-9][A-Za-z0-9_-]*", raw_line)
        )

        if not trimmed or trimmed.startswith(("#", "|", "- ", "* ", "+ ", "> ", "<!--", "---")):
            if trimmed.startswith("#"):
                saw_action_in_section = False
            continue
        if re.match(r"^\d+\.\s", trimmed) or re.match(r"^\d{2}-\d{2}\s+", trimmed):
            continue

        cast_match = re.match(r"^出场人物[：:]\s*(.+)$", trimmed)
        if cast_match:
            for item in re.split(r"[、，,；;。\s]+", cast_match.group(1)):
                if item:
                    speakers.add(item.strip())
            continue

        anchor_match = re.match(r"^([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)[：:]\s*(.+)$", trimmed)
        if anchor_match:
            anchor_id, body = anchor_match.group(1), anchor_match.group(2).strip()
            short_key = anchor_id.rsplit("-", 1)[-1]
            short_counts[short_key] += 1
            short_map[short_key] = anchor_id
            if body.startswith(("△", "▲")):
                action_text = body.lstrip("△▲ \t").strip()
                record = {"id": anchor_id, "kind": "action", "text": action_text}
                anchors[anchor_id] = record
                actions.append({"source_ref": anchor_id, "text": action_text})
                saw_action_in_section = True
            elif body.startswith(("【", "[")):
                anchors[anchor_id] = {"id": anchor_id, "kind": "sound", "text": body}
            else:
                parsed_line = _parse_dialogue_clause(body, source_ref=anchor_id)
                if parsed_line:
                    anchors[anchor_id] = {"id": anchor_id, **parsed_line}
                    dialogues.append(parsed_line)
                else:
                    anchors[anchor_id] = {"id": anchor_id, "kind": "other", "text": body}
            continue

        if trimmed.startswith(("△", "▲")):
            action_text = trimmed.lstrip("△▲ \t").strip()
            if action_text:
                actions.append({"source_ref": None, "text": action_text})
                saw_action_in_section = True
            continue
        if trimmed.startswith(("【", "[")):
            continue

        parsed_line = _parse_dialogue_clause(trimmed, source_ref=None)
        if parsed_line and (
            parsed_line["speaker"] in speakers
            or parsed_line["speaker"] is None
            or parsed_line["modifier"] is not None
            or saw_action_in_section
        ):
            dialogues.append(parsed_line)

    for short_key, count in short_counts.items():
        if count == 1 and short_key not in anchors:
            anchors[short_key] = anchors[short_map[short_key]]

    return {
        "anchors": anchors,
        "actions": actions,
        "dialogues": dialogues,
        "beat_shot_mappings": beat_shot_mappings,
        "ref_line_mappings": ref_line_mappings,
        "referenced_ids": referenced_ids,
    }


def validate_source_script(data, source_text):
    """Cross-check project.json against source script or preproduction handoff markdown."""
    errors = []
    index = entity_index(data)
    groups = {name: {entity["id"]: entity for entity in data[name]} for name in COLLECTIONS}
    known_speakers = {char["name"] for char in data["characters"]}
    parsed = parse_source_script(source_text, known_speakers=known_speakers)
    anchors = parsed["anchors"]

    for ref_id in sorted(parsed["referenced_ids"]):
        if ref_id not in index:
            errors.append(f"源文档引用了不存在的实体 ID：{ref_id}")

    for beat_id, shot_id in parsed["beat_shot_mappings"]:
        shot = groups["shots"].get(shot_id)
        if shot and beat_id not in shot["beat_ids"]:
            errors.append(f"源文档交接映射 {beat_id}→{shot_id} 与分镜实际认领的 beat_ids 不一致")

    for ref_id, line_id in parsed["ref_line_mappings"]:
        line = groups["dialogues"].get(line_id)
        anchor = anchors.get(ref_id)
        if anchor is None:
            errors.append(f"源文档台词映射 {ref_id}→{line_id} 中的源定位 {ref_id} 未找到")
        elif line and normalize_dialogue(anchor.get("text", "")) != normalize_dialogue(line["text"]):
            errors.append(f"{line_id}: 源定位 {ref_id} 台词内容与 JSON 不一致")

    for beat in data["beats"]:
        source_ref = beat.get("source_ref")
        if source_ref:
            for token in (part.strip() for part in re.split(r"[、，,;；\s]+", source_ref) if part.strip()):
                if token not in anchors:
                    errors.append(f"{beat['id']}: source_ref {token} 未在源剧本中找到")

    for line in data["dialogues"]:
        source_ref = line.get("source_ref")
        if source_ref:
            anchor = anchors.get(source_ref.strip())
            if anchor is None:
                errors.append(f"{line['id']}: source_ref {source_ref} 未在源剧本中找到")
            elif normalize_dialogue(anchor.get("text", "")) != normalize_dialogue(line["text"]):
                errors.append(f"{line['id']}: source_ref {source_ref} 的源剧本台词与 JSON 不一致")

    source_dialogues = parsed["dialogues"]
    if len(source_dialogues) != len(data["dialogues"]):
        errors.append(
            f"源剧本台词数量（{len(source_dialogues)}）与 project.json dialogues 数量（{len(data['dialogues'])}）不一致"
        )
    for idx, (src, dst) in enumerate(zip(source_dialogues, data["dialogues"]), 1):
        expected_speaker = groups["characters"][dst["speaker_id"]]["name"] if dst["speaker_id"] else None
        if src["kind"] != dst["kind"]:
            errors.append(f"{dst['id']}: 台词类型与源剧本第{idx}句不一致（源稿：{src['kind']}，JSON：{dst['kind']}）")
        if src["speaker"] != expected_speaker:
            errors.append(
                f"{dst['id']}: 说话角色与源剧本第{idx}句不一致（源稿：{src['speaker'] or '旁白'}，JSON：{expected_speaker or '旁白'}）"
            )
        if normalize_dialogue(src["text"]) != normalize_dialogue(dst["text"]):
            errors.append(
                f"{dst['id']}: 台词内容与源剧本第{idx}句不一致（源稿：「{src['text']}」，JSON：「{dst['text']}」）"
            )
    return errors


def _validate_shared_shape(shared):
    if not isinstance(shared, dict):
        return ["共享资产数据顶层必须为 JSON 对象"]
    schema = load_project(SCHEMA_PATH)
    errors = []
    for name, def_name in (("characters", "character"), ("scenes", "scene"), ("props", "prop"), ("prompts", "prompt")):
        if name not in shared:
            continue
        if not isinstance(shared[name], list):
            errors.append(f"shared.{name}: 类型应为 array")
            continue
        item_schema = schema["$defs"][def_name]
        for index, item in enumerate(shared[name]):
            errors.extend(_shape_errors(item, item_schema, schema, f"shared.{name}[{index}]"))
    return errors


def validate_shared_assets(data, shared):
    """Validate that episode assets and global prompts match a series-level shared assets registry."""
    shape_errors = _validate_shared_shape(shared)
    if shape_errors:
        return [f"共享资产库非法：{err}" for err in shape_errors]
    errors = []
    for collection in ("characters", "scenes", "props"):
        shared_map = {item["id"]: item for item in shared.get(collection, [])}
        for entity in data.get(collection, []):
            target = shared_map.get(entity["id"])
            if target is None:
                continue
            if (entity["revision"] != target["revision"]
                    or entity_fingerprint(entity) != entity_fingerprint(target)):
                errors.append(
                    f"{entity['id']}: 与共享资产库不一致（共享库 revision={target['revision']}，当前 revision={entity['revision']}），请同步共享资产并更新受影响分镜"
                )
    shared_prompts = {
        item["id"]: item for item in shared.get("prompts", []) if item.get("shot_id") is None
    }
    for prompt in data.get("prompts", []):
        if prompt.get("shot_id") is not None:
            continue
        target = shared_prompts.get(prompt["id"])
        if target is None:
            continue
        if (prompt["revision"] != target["revision"]
                or entity_fingerprint(prompt) != entity_fingerprint(target)):
            errors.append(
                f"{prompt['id']}: 全局静态提示词与共享资产库不一致（共享库 revision={target['revision']}，当前 revision={prompt['revision']}）"
            )
    return errors


def sync_shared_assets(data, shared, include_new=False):
    """Synchronize shared characters, scenes, props, and global static prompts into a project."""
    shape_errors = validate_shape(data)
    if shape_errors:
        raise ValueError("\n".join(shape_errors))
    shared_errors = _validate_shared_shape(shared)
    if shared_errors:
        raise ValueError("\n".join(shared_errors))
    result = deepcopy(data)
    for collection in ("characters", "scenes", "props"):
        shared_items = shared.get(collection, [])
        shared_map = {item["id"]: deepcopy(item) for item in shared_items}
        existing_ids = set()
        for index, entity in enumerate(result[collection]):
            existing_ids.add(entity["id"])
            if entity["id"] in shared_map:
                result[collection][index] = deepcopy(shared_map[entity["id"]])
        if include_new:
            for item in shared_items:
                if item["id"] not in existing_ids:
                    result[collection].append(deepcopy(item))
    shared_prompts = [item for item in shared.get("prompts", []) if item.get("shot_id") is None]
    shared_prompt_map = {item["id"]: deepcopy(item) for item in shared_prompts}
    existing_prompt_ids = set()
    for index, prompt in enumerate(result["prompts"]):
        existing_prompt_ids.add(prompt["id"])
        if prompt.get("shot_id") is None and prompt["id"] in shared_prompt_map:
            updated = deepcopy(shared_prompt_map[prompt["id"]])
            updated["depends_on"] = deepcopy(prompt["depends_on"])
            result["prompts"][index] = updated
    if include_new:
        for item in shared_prompts:
            if item["id"] not in existing_prompt_ids:
                result["prompts"].append(deepcopy(item))
    return result


def required_dependencies(data, entity):
    dependencies = {data["project"]["id"]}
    if entity["id"].startswith("SHOT-"):
        for field in ("scene_ids", "character_ids", "prop_ids", "beat_ids"):
            dependencies.update(entity[field])
        for segment in entity["segments"]:
            dependencies.update(line["dialogue_id"] for line in segment["lines"])
    elif entity["id"].startswith("PROMPT-"):
        dependencies.update(entity["asset_ids"])
        dependencies.update(binding["asset_id"] for binding in entity["reference_bindings"])
        if entity["shot_id"]:
            dependencies.add(entity["shot_id"])
    else:
        return set()
    return dependencies


def _collect_dependency_state(data, index):
    derived = data["shots"] + data["prompts"]
    graph = {entity["id"]: required_dependencies(data, entity) for entity in derived}
    errors, stale = [], set()
    for entity in derived:
        entity_id = entity["id"]
        snapshots = entity["depends_on"]
        counts = Counter(snapshot["id"] for snapshot in snapshots)
        expected = graph[entity_id]
        for dependency in sorted(expected - counts.keys()):
            errors.append(f"{entity_id}: 缺少依赖快照 {dependency}")
            stale.add(entity_id)
        for dependency in sorted(counts.keys() - expected):
            errors.append(f"{entity_id}: 多余依赖快照 {dependency}")
            stale.add(entity_id)
        for dependency, count in counts.items():
            if count > 1:
                errors.append(f"{entity_id}: 重复依赖快照 {dependency}")
                stale.add(entity_id)
        for snapshot in snapshots:
            source = index.get(snapshot["id"])
            if source is None:
                errors.append(f"{entity_id}: 依赖快照指向未知实体 {snapshot['id']}")
                stale.add(entity_id)
            elif (snapshot["revision"] != source["revision"]
                  or snapshot["fingerprint"] != entity_fingerprint(source)):
                errors.append(f"{entity_id}: 依赖已失效 {snapshot['id']}，需重建内容并更新快照")
                stale.add(entity_id)
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            errors.append(f"{node}: 依赖成环")
            stale.add(node)
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in sorted(graph.get(node, ())):
            if dependency in graph:
                visit(dependency)
                if dependency in stale:
                    stale.add(node)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    for node in sorted(stale):
        upstream = sorted(graph.get(node, set()) & stale)
        if upstream:
            errors.append(f"{node}: 上游已失效 {', '.join(upstream)}")
    return errors, sorted(stale)


def _dependency_errors(data, index):
    return _collect_dependency_state(data, index)[0]


def find_stale_entities(data):
    """Return sorted IDs of shots and prompts whose dependency snapshots are missing or stale."""
    shape_errors = validate_shape(data)
    if shape_errors:
        raise ValueError("\n".join(shape_errors))
    return _collect_dependency_state(data, entity_index(data))[1]


def _baseline_errors(data, previous):
    errors = []
    previous_errors = validate_shape(previous)
    if previous_errors:
        return [f"基线数据非法：{error}" for error in previous_errors]
    old, current = entity_index(previous), entity_index(data)
    if previous["project"]["id"] != data["project"]["id"]:
        errors.append("基线 project.id 不同，不能跨项目比较")
        return errors
    for entity_id, before in old.items():
        after = current.get(entity_id)
        if after is None:
            errors.append(f"{entity_id}: 基线实体已删除或 ID 已改写，需显式迁移后建立新基线")
            continue
        if after["revision"] < before["revision"]:
            errors.append(f"{entity_id}: revision 相对基线回退")
        elif (entity_fingerprint(before) != entity_fingerprint(after)
              and after["revision"] <= before["revision"]):
            errors.append(f"{entity_id}: 内容已修改但 revision 未增加")
    return errors


def validate_project(data, previous=None, *, source_text=None, shared_assets=None):
    errors, warnings = validate_shape(data), []
    if errors:
        return errors, warnings
    entities = [data["project"]] + [entity for name in COLLECTIONS for entity in data[name]]
    duplicates = [entity_id for entity_id, count in Counter(e["id"] for e in entities).items()
                  if count > 1]
    if duplicates:
        return [f"全局 ID 重复：{entity_id}" for entity_id in duplicates], warnings
    index = entity_index(data)
    groups = {name: {entity["id"]: entity for entity in data[name]} for name in COLLECTIONS}

    def reference(entity_id, allowed, context):
        if entity_id not in allowed:
            errors.append(f"{context}: 未知或类型不符的引用 {entity_id}")
            return None
        return allowed[entity_id]

    for beat in data["beats"]:
        reference(beat["scene_id"], groups["scenes"], beat["id"])
        for field, group in (("character_ids", "characters"), ("prop_ids", "props")):
            for target in beat[field]:
                reference(target, groups[group], beat["id"])
    for line in data["dialogues"]:
        beat = reference(line["beat_id"], groups["beats"], line["id"])
        speaker = line["speaker_id"]
        if speaker is None and line["kind"] != "narration":
            errors.append(f"{line['id']}: dialogue/os 必须指定说话角色")
        if speaker is not None:
            reference(speaker, groups["characters"], line["id"])
            if beat and speaker not in beat["character_ids"]:
                errors.append(f"{line['id']}: 说话角色未登记在对应节拍")

    covered, spoken, dialogue_order = set(), [], []
    dynamic_owners = Counter()
    seen_designs = {}
    for shot in data["shots"]:
        shot_id = shot["id"]
        for field, group in (("scene_ids", "scenes"), ("character_ids", "characters"),
                             ("prop_ids", "props"), ("beat_ids", "beats")):
            for target in shot[field]:
                reference(target, groups[group], shot_id)
        covered.update(shot["beat_ids"])
        for beat_id in shot["beat_ids"]:
            beat = groups["beats"].get(beat_id)
            if not beat:
                continue
            if beat["scene_id"] not in shot["scene_ids"]:
                errors.append(f"{shot_id}: 未承接节拍 {beat_id} 的场景")
            for field in ("character_ids", "prop_ids"):
                missing = set(beat[field]) - set(shot[field])
                if missing:
                    errors.append(f"{shot_id}: 未承接节拍 {beat_id} 的 {field}: {', '.join(sorted(missing))}")
        roles = Counter(design["role"] for design in shot["design"])
        if set(roles) != set(DESIGN_ROLES) or any(count != 1 for count in roles.values()):
            errors.append(f"{shot_id}: design 必须包含八个不同岗位")
        else:
            design_signature = tuple(
                (item["role"], item["decision"].strip())
                for item in sorted(shot["design"], key=lambda item: item["role"])
            )
            if design_signature in seen_designs:
                warnings.append(
                    f"{shot_id}: 八岗位设计决策与 {seen_designs[design_signature]} 完全相同，请结合本镜动作与叙事差异化设计"
                )
            else:
                seen_designs[design_signature] = shot_id
        last_end = Decimal("0")
        for number, segment in enumerate(shot["segments"], 1):
            start, end = Decimal(str(segment["start"])), Decimal(str(segment["end"]))
            if segment["index"] != number:
                errors.append(f"{shot_id}: segments 序号必须从1连续递增")
            if start != last_end:
                errors.append(f"{shot_id}: 镜头{number}起点应为 {last_end}，实际为 {start}")
            if end <= start:
                errors.append(f"{shot_id}: 镜头{number}时长必须为正")
            if start % Decimal("0.1") or end % Decimal("0.1"):
                errors.append(f"{shot_id}: 镜头{number}时间最多保留一位小数")
            last_end = end
            for delivery in segment["lines"]:
                line_id = delivery["dialogue_id"]
                spoken.append(line_id)
                line = reference(line_id, groups["dialogues"], shot_id)
                if not line:
                    continue
                dialogue_order.append(line_id)
                if normalize_dialogue(delivery["text"]) != normalize_dialogue(line["text"]):
                    errors.append(f"{shot_id}: 台词 {line_id} 未逐字继承")
                if line["beat_id"] not in shot["beat_ids"]:
                    errors.append(f"{shot_id}: 台词 {line_id} 不属于本镜认领的节拍")
                if line["speaker_id"] and line["speaker_id"] not in shot["character_ids"]:
                    errors.append(f"{shot_id}: 台词 {line_id} 的说话角色未引用")
        if last_end != Decimal(str(shot["duration"])):
            errors.append(f"{shot_id}: segments 总时长与 duration 不一致")
        for prompt_id in shot["static_prompt_ids"]:
            prompt = reference(prompt_id, groups["prompts"], shot_id)
            if prompt:
                if prompt["template"] not in STATIC_TEMPLATES:
                    errors.append(f"{shot_id}: static_prompt_ids 只能引用静态提示词")
                if prompt["shot_id"] not in (None, shot_id):
                    errors.append(f"{shot_id}: 静态提示词 {prompt_id} 属于另一分镜")
        dynamic_id = shot["dynamic_prompt_id"]
        dynamic_owners[dynamic_id] += 1
        prompt = reference(dynamic_id, groups["prompts"], shot_id)
        if prompt and (prompt["template"] not in DYNAMIC_TEMPLATES or prompt["shot_id"] != shot_id):
            errors.append(f"{shot_id}: dynamic_prompt_id 未指向本镜的动态提示词")

    for beat_id in groups["beats"].keys() - covered:
        errors.append(f"剧情节拍未覆盖：{beat_id}")
    counts = Counter(spoken)
    for line_id in groups["dialogues"]:
        if counts[line_id] != 1:
            errors.append(f"台词 {line_id} 应使用一次，实际 {counts[line_id]} 次")
    expected_order = [line["id"] for line in data["dialogues"]]
    if dialogue_order != expected_order:
        errors.append("台词执行顺序与剧本 dialogues 顺序不一致")

    assets = {**groups["characters"], **groups["scenes"], **groups["props"]}
    referenceable = {**assets, **groups["prompts"]}
    for prompt in data["prompts"]:
        prompt_id = prompt["id"]
        shot = None
        if prompt["shot_id"]:
            shot = reference(prompt["shot_id"], groups["shots"], prompt_id)
            if shot and prompt_id not in shot["static_prompt_ids"] + [shot["dynamic_prompt_id"]]:
                errors.append(f"{prompt_id}: 所属分镜未登记此提示词")
        dynamic = prompt["template"] in DYNAMIC_TEMPLATES
        if dynamic:
            if not shot or dynamic_owners[prompt_id] != 1:
                errors.append(f"{prompt_id}: 动态提示词必须唯一归属一个分镜")
            if shot and prompt["duration"] != shot["duration"]:
                errors.append(f"{prompt_id}: duration 与所属分镜不一致")
            if shot:
                required_assets = set(shot["character_ids"] + shot["scene_ids"] + shot["prop_ids"])
                if required_assets - set(prompt["asset_ids"]):
                    errors.append(f"{prompt_id}: 未完整登记本镜资产")
        elif prompt["duration"] is not None:
            errors.append(f"{prompt_id}: 静态提示词 duration 必须为 null")
        for asset_id in prompt["asset_ids"]:
            reference(asset_id, assets, prompt_id)
        slots = [binding["slot"] for binding in prompt["reference_bindings"]]
        if len(slots) != len(set(slots)):
            errors.append(f"{prompt_id}: 素材位重复")
        prefix = "@素材" if dynamic else "@图片"
        for binding in prompt["reference_bindings"]:
            asset_id = binding["asset_id"]
            target = reference(asset_id, referenceable, prompt_id)
            if not binding["slot"].startswith(prefix):
                errors.append(f"{prompt_id}: 模板应使用 {prefix}N 素材位")
            if target and asset_id in groups["prompts"]:
                if target["template"] not in STATIC_TEMPLATES:
                    errors.append(f"{prompt_id}: 参考图不能引用动态提示词 {asset_id}")
            elif asset_id not in prompt["asset_ids"]:
                errors.append(f"{prompt_id}: 绑定资产 {asset_id} 未列入 asset_ids")
        used_slots = set(re.findall(r"@(?:素材|图片)[1-9]\d*", prompt["text"]))
        if used_slots != set(slots):
            errors.append(f"{prompt_id}: 正文素材位与 reference_bindings 不一致")
        fixed_ratios = {"T1": "16:9", "T2": "3:4", "T3": "16:9",
                        "T4": "16:9", "T6": "16:9", "T6B": "16:9"}
        ratio = fixed_ratios.get(prompt["template"], data["project"]["aspect_ratio"])
        ratio_lines = re.findall(r"(?m)^--ar[ \t]+([^\r\n]+)", prompt["text"])
        if ratio_lines != [ratio] or not prompt["text"].rstrip().endswith("--ar " + ratio):
            errors.append(f"{prompt_id}: 画幅须在末行唯一声明 --ar {ratio}")
    errors.extend(_dependency_errors(data, index))
    if previous is not None:
        errors.extend(_baseline_errors(data, previous))
    if source_text is not None:
        errors.extend(validate_source_script(data, source_text))
    if shared_assets is not None:
        errors.extend(validate_shared_assets(data, shared_assets))
    return errors, warnings


def snapshot_dependencies(data, entity_ids=None):
    """Explicitly capture rebuilt entities; never called by validation or rendering."""
    shape_errors = validate_shape(data)
    if shape_errors:
        raise ValueError("\n".join(shape_errors))
    result = deepcopy(data)
    index = entity_index(result)
    derived = {entity["id"]: entity for entity in result["shots"] + result["prompts"]}
    selected = set(derived if entity_ids is None else entity_ids)
    unknown = selected - derived.keys()
    if unknown:
        raise ValueError(f"只能捕获分镜或提示词：{', '.join(sorted(unknown))}")
    done, active = set(), set()

    def capture(entity_id):
        if entity_id in done:
            return
        if entity_id in active:
            raise ValueError(f"依赖成环：{entity_id}")
        active.add(entity_id)
        entity = derived[entity_id]
        dependencies = required_dependencies(result, entity)
        missing = dependencies - index.keys()
        if missing:
            raise ValueError(f"{entity_id}: 未知依赖 {', '.join(sorted(missing))}")
        for source_id in sorted(dependencies):
            if source_id in selected:
                capture(source_id)
        entity["depends_on"] = [
            {"id": source_id, "revision": index[source_id]["revision"],
             "fingerprint": entity_fingerprint(index[source_id])}
            for source_id in sorted(dependencies)
        ]
        active.remove(entity_id)
        done.add(entity_id)

    for entity_id in sorted(selected):
        capture(entity_id)
    dependency_errors = _dependency_errors(result, entity_index(result))
    relevant = [error for error in dependency_errors
                if any(error.startswith(entity_id + ":") for entity_id in selected)]
    if relevant:
        raise ValueError("\n".join(relevant))
    return result


def _write_json(data, target_path, in_place=False):
    output = Path(target_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if in_place else "x"
    with output.open(mode, encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    capture_parser = sub.add_parser("capture", help="显式记录已重做实体的当前依赖")
    capture_parser.add_argument("project")
    capture_parser.add_argument("--entity", action="append", help="指定已重做的 SHOT-* 或 PROMPT-* ID（可多次传入）")
    capture_parser.add_argument("--all", action="store_true", help="捕获全部衍生分镜与提示词的依赖快照")
    capture_parser.add_argument("--stale", action="store_true", help="自动识别并捕获当前缺少快照或依赖已失效的分镜与提示词")
    capture_out = capture_parser.add_mutually_exclusive_group(required=True)
    capture_out.add_argument("--output", help="输出新文件路径（不得覆盖已有文件）")
    capture_out.add_argument("-i", "--in-place", action="store_true", help="原地更新输入 JSON 文件")

    sync_parser = sub.add_parser("sync-assets", help="从共享资产库或上游项目同步角色、场景、道具及全局静态提示词")
    sync_parser.add_argument("project")
    sync_parser.add_argument("--from", dest="shared", required=True, help="共享资产 JSON 或上游 project.json")
    sync_parser.add_argument("--include-new", action="store_true", help="同时并入当前项目尚未收录的新共享资产")
    sync_out = sync_parser.add_mutually_exclusive_group(required=True)
    sync_out.add_argument("--output", help="输出新文件路径（不得覆盖已有文件）")
    sync_out.add_argument("-i", "--in-place", action="store_true", help="原地更新输入 JSON 文件")

    extract_parser = sub.add_parser("extract-script", help="从源剧本或前期交接 Markdown 提取动作与台词结构")
    extract_parser.add_argument("source", help="源剧本或交接 Markdown 文件路径")
    extract_parser.add_argument("--output", help="可选输出 JSON 文件路径（缺省打印到 stdout）")

    args = parser.parse_args(argv)
    if args.command == "capture":
        choices = bool(args.entity) + bool(args.all) + bool(args.stale)
        if choices == 0:
            capture_parser.error("必须指定 --entity、--all 或 --stale 之一")
        if choices > 1:
            capture_parser.error("--entity、--all 与 --stale 不能同时使用")
    try:
        if args.command == "capture":
            raw = load_project(args.project)
            if args.all:
                selected = None
            elif args.stale:
                selected = find_stale_entities(raw)
            else:
                selected = args.entity
            data = snapshot_dependencies(raw, selected)
            target = args.project if args.in_place else args.output
            output = _write_json(data, target, in_place=args.in_place)
            print(f"已记录依赖：{output}")
            return 0
        if args.command == "sync-assets":
            raw = load_project(args.project)
            shared = load_project(args.shared)
            data = sync_shared_assets(raw, shared, include_new=args.include_new)
            target = args.project if args.in_place else args.output
            output = _write_json(data, target, in_place=args.in_place)
            print(f"已同步共享资产：{output}")
            return 0
        if args.command == "extract-script":
            source_text = Path(args.source).read_text(encoding="utf-8-sig")
            parsed = parse_source_script(source_text)
            payload = {
                "actions": parsed["actions"],
                "dialogues": parsed["dialogues"],
                "beat_shot_mappings": [
                    {"beat_id": beat_id, "shot_id": shot_id}
                    for beat_id, shot_id in parsed["beat_shot_mappings"]
                ],
                "ref_line_mappings": [
                    {"source_ref": ref_id, "dialogue_id": line_id}
                    for ref_id, line_id in parsed["ref_line_mappings"]
                ],
            }
            if args.output:
                output = _write_json(payload, args.output, in_place=False)
                print(f"已提取源剧本骨架：{output}")
            else:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        return 2
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
