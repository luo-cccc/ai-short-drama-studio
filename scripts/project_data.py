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
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import wave

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "project.schema.json"
COLLECTIONS = ("characters", "scenes", "props", "beats", "dialogues", "shots", "prompts", "voices")
STATIC_TEMPLATES = {"T1", "T2", "T3", "T4", "T5", "T6", "T6B", "T6C"}
DYNAMIC_TEMPLATES = {"T7", "T8", "T9"}
DESIGN_ROLES = ("director", "camera", "lighting", "action", "staging", "dialogue", "sound", "vfx")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 键：{key}")
        result[key] = value
    return result


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"非有限数值：{value}")
    return result


def parse_project(text):
    return json.loads(text.lstrip("\ufeff"), object_pairs_hook=_unique_object,
                      parse_float=_finite_float,
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
    errors = list(_shape_errors(data, schema, schema))
    if not errors and data["schema_version"] == "1.0":
        if "voices" in data or any(
                "audio_reference_profile" in prompt
                or any(binding["asset_id"].startswith("VOICE-") or "audio_reference_id" in binding
                       for binding in prompt["reference_bindings"])
                or any(asset.startswith("VOICE-") for asset in prompt["asset_ids"])
                for prompt in data["prompts"]):
            errors.append("$.schema_version: 声音参考字段需要版本 1.1")
    return errors


def entity_index(data):
    entities = [data["project"]]
    for collection in COLLECTIONS:
        entities.extend(data.get(collection, []))
    duplicates = [entity_id for entity_id, count in Counter(entity["id"] for entity in entities).items() if count > 1]
    if duplicates:
        raise ValueError("\n".join(f"全局 ID 重复：{entity_id}" for entity_id in duplicates))
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
    if speaker in {"旁白", "NAR", "画外音", "叙述者"}:
        kind, speaker_name = "narration", None
    elif re.search(r"\bNAR\b|旁白", modifier, re.I):
        kind, speaker_name = "narration", speaker
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
    referenced_ids, errors = set(), []
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
                fence_marker = marker
                in_ignored_fence = lang in {"json", "python", "powershell", "bash", "sh", "cmd", "yaml"}
            elif marker[0] == fence_marker[0] and len(marker) >= len(fence_marker) and not lang:
                in_ignored_fence = False
                fence_marker = None
            continue
        if in_ignored_fence:
            continue

        for beat_id, shot_id in re.findall(r"(?<![A-Za-z0-9_-])(BEAT-[A-Za-z0-9_-]+)\s*(?:→|->)\s*(SHOT-[A-Za-z0-9_-]+)", raw_line):
            beat_shot_mappings.append((beat_id, shot_id))
        for ref_id, line_id in re.findall(r"(?<![A-Za-z0-9_-])([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s*(?:→|->)\s*(LINE-[A-Za-z0-9_-]+)", raw_line):
            if not ref_id.startswith(("BEAT-", "SHOT-", "CHAR-", "SCENE-", "PROP-", "PROMPT-", "PRJ-", "VOICE-")):
                ref_line_mappings.append((ref_id, line_id))
        referenced_ids.update(
            re.findall(r"(?<![A-Za-z0-9_-])(?:PRJ|CHAR|SCENE|PROP|BEAT|LINE|SHOT|PROMPT|VOICE)-[A-Za-z0-9][A-Za-z0-9_-]*", raw_line)
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
            if anchor_id in anchors:
                errors.append(f"源剧本定位 ID 重复：{anchor_id}")
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
        "errors": errors,
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
    groups = {name: {entity["id"]: entity for entity in data.get(name, [])} for name in COLLECTIONS}
    known_speakers = {char["name"] for char in data["characters"]}
    parsed = parse_source_script(source_text, known_speakers=known_speakers)
    anchors = parsed["anchors"]
    errors.extend(parsed["errors"])

    def check_anchor_identity(anchor, line, label):
        if anchor.get("kind") not in {"dialogue", "os", "narration"}:
            errors.append(f"{line['id']}: {label} 必须指向台词，不能指向动作、音效或说明")
            return
        if anchor["kind"] != line["kind"]:
            errors.append(f"{line['id']}: {label} 的台词类型与 JSON 不一致")
        speaker = groups["characters"].get(line["speaker_id"])
        expected_speaker = speaker["name"] if speaker else None
        if anchor["speaker"] != expected_speaker:
            errors.append(f"{line['id']}: {label} 的说话角色与 JSON 不一致")

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
        elif line:
            check_anchor_identity(anchor, line, f"源定位 {ref_id}")
            if normalize_dialogue(anchor.get("text", "")) != normalize_dialogue(line["text"]):
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
            else:
                check_anchor_identity(anchor, line, f"source_ref {source_ref}")
                if normalize_dialogue(anchor.get("text", "")) != normalize_dialogue(line["text"]):
                    errors.append(f"{line['id']}: source_ref {source_ref} 的源剧本台词与 JSON 不一致")

    source_dialogues = parsed["dialogues"]
    if len(source_dialogues) != len(data["dialogues"]):
        errors.append(
            f"源剧本台词数量（{len(source_dialogues)}）与 project.json dialogues 数量（{len(data['dialogues'])}）不一致"
        )
    for idx, (src, dst) in enumerate(zip(source_dialogues, data["dialogues"]), 1):
        speaker_id = dst["speaker_id"]
        character = groups["characters"].get(speaker_id) if speaker_id else None
        expected_speaker = character["name"] if character else None
        if speaker_id is not None and character is None:
            errors.append(f"{dst['id']}: 源剧本说话人对账失败，未知说话角色 {speaker_id}")
        if src["kind"] != dst["kind"]:
            errors.append(f"{dst['id']}: 台词类型与源剧本第{idx}句不一致（源稿：{src['kind']}，JSON：{dst['kind']}）")
        if (speaker_id is None or character is not None) and src["speaker"] != expected_speaker:
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
    seen_ids = {}
    for name, def_name in (("characters", "character"), ("scenes", "scene"), ("props", "prop"), ("voices", "voice"), ("prompts", "prompt")):
        if name not in shared:
            continue
        if not isinstance(shared[name], list):
            errors.append(f"shared.{name}: 类型应为 array")
            continue
        item_schema = schema["$defs"][def_name]
        for index, item in enumerate(shared[name]):
            item_path = f"shared.{name}[{index}]"
            errors.extend(_shape_errors(item, item_schema, schema, item_path))
            if (name == "prompts" and isinstance(item, dict) and item.get("shot_id") is None
                    and item.get("template") not in STATIC_TEMPLATES):
                errors.append(f"{item_path}: 全局共享提示词必须使用静态模板")
            entity_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(entity_id, str):
                if entity_id in seen_ids:
                    errors.append(f"{item_path}.id: 共享资产全局 ID 重复：{entity_id}（首次见于 {seen_ids[entity_id]}）")
                else:
                    seen_ids[entity_id] = item_path
    return errors


def validate_shared_assets(data, shared):
    """Validate that episode assets and global prompts match a series-level shared assets registry."""
    shape_errors = _validate_shared_shape(shared)
    if shape_errors:
        return [f"共享资产库非法：{err}" for err in shape_errors]
    errors = []
    for collection in ("characters", "scenes", "props", "voices"):
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
    """Synchronize shared assets, including voice references, and global static prompts."""
    shape_errors = validate_shape(data)
    if shape_errors:
        raise ValueError("\n".join(shape_errors))
    entity_index(data)  # Refuse ambiguous identities before replacing any shared data.
    shared_errors = _validate_shared_shape(shared)
    if shared_errors:
        raise ValueError("\n".join(shared_errors))
    result = deepcopy(data)
    for collection in ("characters", "scenes", "props", "voices"):
        shared_items = shared.get(collection, [])
        shared_map = {item["id"]: deepcopy(item) for item in shared_items}
        existing_ids = set()
        for index, entity in enumerate(result.get(collection, [])):
            existing_ids.add(entity["id"])
            if entity["id"] in shared_map:
                result[collection][index] = deepcopy(shared_map[entity["id"]])
        if include_new:
            for item in shared_items:
                if item["id"] not in existing_ids:
                    result.setdefault(collection, []).append(deepcopy(item))
                    existing_ids.add(item["id"])
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
                existing_prompt_ids.add(item["id"])
    if "voices" in result or any("audio_reference_profile" in prompt for prompt in result["prompts"]):
        result["schema_version"] = "1.1"
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
    try:
        old, current = entity_index(previous), entity_index(data)
    except ValueError as error:
        return [f"基线数据非法：{error}"]
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


def _validate_voices(data):
    errors, warnings = [], []
    characters = {item["id"] for item in data["characters"]}
    for voice in data.get("voices", []):
        voice_id, master = voice["id"], voice["master"]
        if voice["character_id"] is not None and voice["character_id"] not in characters:
            errors.append(f"{voice_id}: 未知角色 {voice['character_id']}")
        if voice["status"] == "planned":
            if master is not None or voice["references"]:
                errors.append(f"{voice_id}: planned 声音不能登记已就绪母版或投喂副本")
            if voice["audition"] == "approved":
                errors.append(f"{voice_id}: planned 声音不能标记试听已通过")
            warnings.append(f"{voice_id}: 声音待制作，尚无可投喂音频，不得分配音频素材槽")
        elif master is None:
            errors.append(f"{voice_id}: ready 声音必须登记母版音频")
        if voice["status"] == "ready" and voice["audition"] != "approved":
            warnings.append(f"{voice_id}: 声音试听状态为 {voice['audition']}，需结合实际音频复核")
        reference_ids = [item["id"] for item in voice["references"]]
        if len(reference_ids) != len(set(reference_ids)):
            errors.append(f"{voice_id}: 投喂副本 id 重复")
        for item in voice["references"]:
            start, end = Decimal(str(item["source_start"])), Decimal(str(item["source_end"]))
            if end <= start:
                errors.append(f"{voice_id}/{item['id']}: 母版裁剪区间必须为正")
            if master is not None and end > Decimal(str(master["duration"])):
                errors.append(f"{voice_id}/{item['id']}: 裁剪区间超出母版时长")
            if abs(end - start - Decimal(str(item["duration"]))) > Decimal("0.05"):
                errors.append(f"{voice_id}/{item['id']}: 副本时长与母版裁剪区间不一致（不隐式变速）")
        for item in ([master] if master is not None else []) + voice["references"]:
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", item["path"]):
                errors.append(f"{voice_id}: 音频 path 应登记本地文件路径，不能使用远程 URL")
    return errors, warnings


def _validate_voice_bindings(data, prompt, shot, groups):
    errors, warnings = [], []
    prompt_id = prompt["id"]
    bindings = [item for item in prompt["reference_bindings"] if item["asset_id"].startswith("VOICE-")]
    voice_assets = {item for item in prompt["asset_ids"] if item.startswith("VOICE-")}
    bound_ids = {item["asset_id"] for item in bindings}
    profile = prompt.get("audio_reference_profile")
    dynamic = prompt["template"] in DYNAMIC_TEMPLATES
    if not dynamic and (voice_assets or bindings or profile is not None):
        errors.append(f"{prompt_id}: 静态提示词不能使用声音资产或音频参考配置")
    if voice_assets - bound_ids:
        errors.append(f"{prompt_id}: 声音资产缺少音频素材绑定：{', '.join(sorted(voice_assets - bound_ids))}")
    if bindings and profile is None:
        errors.append(f"{prompt_id}: 声音绑定必须声明 audio_reference_profile 及目标视频模型")
    if bindings and profile is not None and not profile["supports_voice_reference"]:
        errors.append(f"{prompt_id}: 目标模型声明不支持声音参考，不能投喂声音槽")
    for item in prompt["reference_bindings"]:
        if not item["asset_id"].startswith("VOICE-") and "audio_reference_id" in item:
            errors.append(f"{prompt_id}: 只有声音绑定可以指定 audio_reference_id")
        if not item["asset_id"].startswith("VOICE-"):
            declaration = re.search(
                r"(?m)^[ \t]*" + re.escape(item["slot"]) + r"[ \t]+参考([^\r\n]+)", prompt["text"]
            )
            if declaration:
                positive = re.split(
                    r"禁止\s*继承|不继承|不参考|不包含|不采纳|禁止参考|排除|不使用|[。！？]",
                    declaration.group(1), maxsplit=1,
                )[0]
                if re.search(r"声音身份|音色|声线", positive):
                    errors.append(f"{prompt_id}/{item['slot']}: 声音身份参考声明必须绑定 VOICE- 音频资产")
    durations, owners = [], []
    line_ids = {line["dialogue_id"] for segment in shot["segments"] for line in segment["lines"]} if shot else set()
    lines = [groups["dialogues"][line_id] for line_id in line_ids if line_id in groups["dialogues"]]
    speakers = {line["speaker_id"] for line in lines}
    for binding in bindings:
        voice = groups["voices"].get(binding["asset_id"])
        if voice is None:
            continue  # General reference validation reports the missing asset.
        context = f"{prompt_id}/{binding['slot']}"
        if voice["status"] != "ready":
            errors.append(f"{context}: 声音 {voice['id']} 尚未 ready，不能分配音频素材槽")
        owner = voice["character_id"]
        owners.append(owner)
        if owner is None:
            if not any(line["kind"] == "narration" and line["speaker_id"] is None for line in lines):
                errors.append(f"{context}: 旁白声音未对应本镜无角色旁白")
            expected_name = voice["name"]
            expected_names = (expected_name, "旁白", "NAR", "叙述者")
        else:
            character = groups["characters"].get(owner)
            expected_name = character["name"] if character else owner
            expected_names = (expected_name,)
            if shot and owner not in shot["character_ids"]:
                errors.append(f"{context}: 声音角色 {owner} 未登记在本镜")
            elif owner not in speakers:
                warnings.append(f"{context}: 角色本镜没有已登记台词，确认是否需要该声音参考")
        declaration = re.search(
            r"(?m)^[ \t]*" + re.escape(binding["slot"]) + r"[ \t]+参考[^\r\n]+", prompt["text"]
        )
        declaration_body = declaration.group().split("参考", 1)[1].strip() if declaration else ""
        positive_subject = re.split(
            r"禁止\s*继承|不继承|不参考|不包含|不采纳|禁止参考|排除|不使用|[。！？]",
            declaration_body, maxsplit=1,
        )[0]
        if not declaration or not re.search(r"声音|音色|声线|音频", positive_subject):
            errors.append(f"{context}: 缺少明确的声音身份参考声明")
        elif not any(name in positive_subject for name in expected_names):
            errors.append(f"{context}: 声音参考声明未明确所属角色或旁白 {expected_name}")
        elif not re.match(r"(?:角色|人物)?\s*(?:" + "|".join(re.escape(name) for name in expected_names) + r")(?:的)?\s*(?:声音身份|声音|音色|声线|音频)", positive_subject):
            warnings.append(f"{context}: 声音参考主语未使用明确角色协议，请核对声音归属 {expected_name}")
        reference_id = binding.get("audio_reference_id")
        selected = next((item for item in voice["references"] if item["id"] == reference_id), None)
        if selected is None:
            errors.append(f"{context}: audio_reference_id 未指向该声音的投喂副本")
            continue
        durations.append(Decimal(str(selected["duration"])))
        if profile is None:
            continue
        if selected["model_id"] != profile["model_id"]:
            errors.append(f"{context}: 声音副本 model_id 与目标视频模型不一致")
        maximum = profile["max_file_duration"]
        if maximum is not None and Decimal(str(selected["duration"])) > Decimal(str(maximum)):
            errors.append(f"{context}: 声音副本超过单文件时长上限")
        extension = Path(selected["path"]).suffix.lower().lstrip(".")
        if profile["formats"] and extension not in profile["formats"]:
            errors.append(f"{context}: 音频格式 {extension or '未知'} 不在目标模型允许范围")
    voices_by_slot = {item["slot"]: groups["voices"].get(item["asset_id"]) for item in bindings}
    for character in groups["characters"].values():
        role_pattern = r"(?m)^[ \t]*角色" + re.escape(character["name"]) + r"[：:][^\r\n]+"
        for role_line in re.finditer(role_pattern, prompt["text"]):
            for match in re.finditer(r"(?:声音身份|声音|音色|声线)[ \t]*参考[ \t]*(@素材[1-9]\d*)", role_line.group()):
                slot = match.group(1)
                target = voices_by_slot.get(slot)
                if target is None:
                    errors.append(f"{prompt_id}: 角色{character['name']}的声音槽 {slot} 未绑定声音资产")
                elif target["character_id"] != character["id"]:
                    errors.append(f"{prompt_id}: 角色{character['name']}的声音槽 {slot} 指向其他角色或旁白")
    if len(owners) != len(set(owners)):
        errors.append(f"{prompt_id}: 同一角色或旁白被绑定多个声音参考，请明确单一身份或调整分段")
    if bindings and profile is not None:
        if profile["max_files"] is not None and len(bindings) > profile["max_files"]:
            errors.append(f"{prompt_id}: 声音参考数量超过目标模型上限")
        if profile["max_total_duration"] is not None and sum(durations) > Decimal(str(profile["max_total_duration"])):
            errors.append(f"{prompt_id}: 声音参考总时长超过目标模型上限")
        if any(profile[field] is None for field in ("max_files", "max_file_duration", "max_total_duration")) or not profile["formats"]:
            warnings.append(f"{prompt_id}: 目标模型声音参考限制存在未核验项，投喂前核对实际接口")
    return errors, warnings


def validate_voice_media(data, media_root):
    """Check registered local audio bytes; this does not verify speech identity or quality."""
    shape_errors = validate_shape(data)
    if shape_errors:
        return shape_errors, []
    errors, warnings = [], []
    root = Path(media_root)
    if not root.is_dir():
        return [f"声音媒体根目录不存在或不是目录：{root}"], []
    for voice in data.get("voices", []):
        records = ([('master', voice["master"])] if voice["master"] is not None else [])
        records.extend((item["id"], item) for item in voice["references"])
        for label, record in records:
            context = f"{voice['id']}/{label}"
            path = root / record["path"]
            try:
                fingerprint = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        fingerprint.update(chunk)
                if fingerprint.hexdigest() != record["sha256"]:
                    errors.append(f"{context}: 音频文件 SHA-256 与登记指纹不符：{path}")
                if path.suffix.lower() == ".wav":
                    with wave.open(str(path), "rb") as audio:
                        if audio.getframerate() <= 0:
                            raise ValueError("WAV 采样率必须为正")
                        duration = audio.getnframes() / audio.getframerate()
                        expected_bytes = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                        if len(audio.readframes(audio.getnframes())) != expected_bytes:
                            errors.append(f"{context}: WAV 音频数据截断：{path}")
                    if abs(Decimal(str(duration)) - Decimal(str(record["duration"]))) > Decimal("0.05"):
                        errors.append(f"{context}: WAV 实测时长与登记时长不符：{path}")
                else:
                    warnings.append(f"{context}: 已检查文件和指纹；标准库未测量 {path.suffix} 音频时长")
            except (OSError, ValueError, EOFError, wave.Error) as error:
                errors.append(f"{context}: 无法检查音频文件 {path}：{error}")
    return errors, warnings


def validate_project(data, previous=None, *, source_text=None, shared_assets=None):
    errors, warnings = validate_shape(data), []
    if errors:
        return errors, warnings
    entities = [data["project"]] + [entity for name in COLLECTIONS for entity in data.get(name, [])]
    duplicates = [entity_id for entity_id, count in Counter(e["id"] for e in entities).items()
                  if count > 1]
    if duplicates:
        return [f"全局 ID 重复：{entity_id}" for entity_id in duplicates], warnings
    index = entity_index(data)
    groups = {name: {entity["id"]: entity for entity in data.get(name, [])} for name in COLLECTIONS}
    voice_errors, voice_warnings = _validate_voices(data)
    errors.extend(voice_errors)
    warnings.extend(voice_warnings)

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
        last_cue_start = None
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
                has_cue_start, has_cue_end = "start" in delivery, "end" in delivery
                if has_cue_start != has_cue_end:
                    errors.append(f"{shot_id}: 台词 {line_id} 的 start/end 必须成对填写或同时省略")
                elif has_cue_start:
                    cue_start = Decimal(str(delivery["start"]))
                    cue_end = Decimal(str(delivery["end"]))
                    if cue_end <= cue_start:
                        errors.append(f"{shot_id}: 台词 {line_id} 的 end 必须大于 start")
                    if not start <= cue_start < end:
                        errors.append(f"{shot_id}: 台词 {line_id} 的 start 必须落在所属镜头的 [{start}, {end}) 内")
                    if cue_end > Decimal(str(shot["duration"])):
                        errors.append(f"{shot_id}: 台词 {line_id} 的 end 不得超过分镜 duration")
                    if last_cue_start is not None and cue_start < last_cue_start:
                        errors.append(f"{shot_id}: 已标定台词 start 按执行顺序不得回退（{line_id}）")
                    last_cue_start = cue_start
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
        for overlay in shot.get("overlays", []):
            has_ov_start, has_ov_end = "start" in overlay, "end" in overlay
            if has_ov_start != has_ov_end:
                errors.append(f"{shot_id}: overlay「{overlay['text']}」的 start/end 必须成对填写或同时省略")
            elif has_ov_start:
                ov_start, ov_end = Decimal(str(overlay["start"])), Decimal(str(overlay["end"]))
                if ov_end <= ov_start:
                    errors.append(f"{shot_id}: overlay「{overlay['text']}」的 end 必须大于 start")
                if ov_end > Decimal(str(shot["duration"])):
                    errors.append(f"{shot_id}: overlay「{overlay['text']}」的 end 不得超过分镜 duration")
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

    assets = {**groups["characters"], **groups["scenes"], **groups["props"], **groups["voices"]}
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
        voice_errors, voice_warnings = _validate_voice_bindings(data, prompt, shot, groups)
        errors.extend(voice_errors)
        warnings.extend(voice_warnings)
        fixed_ratios = {"T1": "16:9", "T2": "3:4", "T3": "16:9", "T4": "16:9"}
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


def scaffold_project_from_source(source_text):
    """Build a valid, dependency-captured project.json draft skeleton from a source script or handoff markdown."""
    parsed = parse_source_script(source_text)
    if parsed["errors"]:
        raise ValueError("\n".join(parsed["errors"]))

    referenced = parsed["referenced_ids"]
    prj_ids = sorted(i for i in referenced if i.startswith("PRJ-"))
    project_id = prj_ids[0] if prj_ids else "PRJ-DRAFT"

    title_match = re.search(r"(?m)^#\s+([^\r\n]+)", source_text)
    raw_title = title_match.group(1).strip() if title_match else "未命名短剧"
    title = raw_title.split("·")[0].strip() or raw_title

    aspect_ratio = "9:16"
    for ratio in ("9:16", "16:9", "2.39:1"):
        if ratio in source_text:
            aspect_ratio = ratio
            break

    char_map, scene_map, prop_map = {}, {}, {}
    for line in source_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            label, asset_cell = cells[0], cells[1]
            for asset_id in re.findall(r"(?:CHAR|SCENE|PROP)-[A-Za-z0-9][A-Za-z0-9_-]*", asset_cell):
                primary_name = re.split(r"[、，,;；\s]+", label)[0].strip() or asset_id
                if asset_id.startswith("CHAR-") and asset_id not in char_map:
                    char_map[asset_id] = primary_name
                elif asset_id.startswith("SCENE-") and asset_id not in scene_map:
                    scene_map[asset_id] = primary_name
                elif asset_id.startswith("PROP-") and asset_id not in prop_map:
                    prop_map[asset_id] = primary_name

    for line in source_text.splitlines():
        trimmed = line.strip()
        cast_match = re.search(r"出场人物[：:]\s*([^\n。]+)", trimmed)
        if cast_match:
            for item in re.split(r"[、，,；;。\s]+", cast_match.group(1)):
                name = item.strip()
                if name and name not in char_map.values():
                    cid = f"CHAR-{len(char_map) + 1:03d}"
                    while cid in char_map:
                        cid = f"CHAR-{len(char_map) + 2:03d}"
                    char_map[cid] = name
        prop_match = re.search(r"(?:可操作)?道具[：:]\s*([^\n。]+)", trimmed)
        if prop_match:
            for item in re.split(r"[、，,；;。\s]+", prop_match.group(1)):
                name = item.strip()
                if name and name not in {"无", "暂无"} and name not in prop_map.values():
                    pid = f"PROP-{len(prop_map) + 1:03d}"
                    while pid in prop_map:
                        pid = f"PROP-{len(prop_map) + 2:03d}"
                    prop_map[pid] = name
        scene_hdr = re.match(r"^(?:###\s+\S+\s*·\s*|\d{2}-\d{2}\s+)(?:[^·\n]+·\s*)*([^\s·]+)\s*$", trimmed)
        if scene_hdr:
            sname = scene_hdr.group(1).strip()
            if sname and sname not in scene_map.values():
                sid = f"SCENE-{len(scene_map) + 1:03d}"
                scene_map[sid] = sname

    for dlg in parsed["dialogues"]:
        sp = dlg["speaker"]
        if sp and sp not in char_map.values():
            cid = f"CHAR-{len(char_map) + 1:03d}"
            char_map[cid] = sp

    for ref_id in sorted(referenced):
        if ref_id.startswith("CHAR-") and ref_id not in char_map:
            char_map[ref_id] = ref_id
        elif ref_id.startswith("SCENE-") and ref_id not in scene_map:
            scene_map[ref_id] = ref_id
        elif ref_id.startswith("PROP-") and ref_id not in prop_map:
            prop_map[ref_id] = ref_id

    if not scene_map:
        scene_map["SCENE-001"] = "默认场景"

    name_to_char_id = {name: cid for cid, name in char_map.items()}
    default_scene_id = next(iter(scene_map))

    characters = [
        {
            "id": cid,
            "revision": 1,
            "name": name,
            "description": f"{name}，待补充角色视觉设定与服装固有配色。",
            "voice": "自然稳健声线，咬字清晰。",
        }
        for cid, name in char_map.items()
    ]
    scenes = [
        {
            "id": sid,
            "revision": 1,
            "name": name,
            "description": f"{name}，前景、中景、背景空间边界与固定陈设清晰。",
        }
        for sid, name in scene_map.items()
    ]
    props = [
        {
            "id": pid,
            "revision": 1,
            "name": name,
            "description": f"{name}，结构与材质细节清晰可辨。",
        }
        for pid, name in prop_map.items()
    ]

    beat_shot_pairs = list(parsed["beat_shot_mappings"])
    if not beat_shot_pairs:
        count = max(1, len(parsed["actions"]))
        beat_shot_pairs = [(f"BEAT-{i:03d}", f"SHOT-{i:03d}") for i in range(1, count + 1)]

    ref_to_line_id = dict(parsed["ref_line_mappings"])
    beats = []
    actions = parsed["actions"] or [{"source_ref": None, "text": "待补充剧情动作节拍。"}]
    for idx, (beat_id, _) in enumerate(beat_shot_pairs):
        if any(b["id"] == beat_id for b in beats):
            continue
        act = actions[idx] if idx < len(actions) else actions[-1]
        text = act["text"]
        c_ids = [cid for cid, cname in char_map.items() if cname in text] or list(char_map.keys())[:1]
        p_ids = [pid for pid, pname in prop_map.items() if pname in text]
        beat_entry = {
            "id": beat_id,
            "revision": 1,
            "scene_id": default_scene_id,
            "summary": text,
            "character_ids": c_ids,
            "prop_ids": p_ids,
        }
        if act.get("source_ref"):
            beat_entry["source_ref"] = act["source_ref"]
        beats.append(beat_entry)

    for ref_id in sorted(i for i in referenced if i.startswith("BEAT-")):
        if not any(b["id"] == ref_id for b in beats):
            beats.append({
                "id": ref_id,
                "revision": 1,
                "scene_id": default_scene_id,
                "summary": "待补充节拍摘要。",
                "character_ids": list(char_map.keys())[:1],
                "prop_ids": [],
            })

    dialogues = []
    used_line_ids = set()
    for idx, dlg in enumerate(parsed["dialogues"]):
        sref = dlg.get("source_ref")
        short_ref = sref.rsplit("-", 1)[-1] if sref else None
        line_id = (
            ref_to_line_id.get(sref)
            or (ref_to_line_id.get(short_ref) if short_ref else None)
            or f"LINE-{idx + 1:03d}"
        )
        while line_id in used_line_ids:
            line_id = f"LINE-{len(used_line_ids) + 1:03d}"
        used_line_ids.add(line_id)
        target_beat = beats[min(idx, len(beats) - 1)]
        speaker_id = name_to_char_id.get(dlg["speaker"]) if dlg["speaker"] else None
        if speaker_id and speaker_id not in target_beat["character_ids"]:
            target_beat["character_ids"].append(speaker_id)
        line_entry = {
            "id": line_id,
            "revision": 1,
            "beat_id": target_beat["id"],
            "speaker_id": speaker_id,
            "kind": dlg["kind"],
            "text": dlg["text"],
        }
        if sref:
            line_entry["source_ref"] = sref
        dialogues.append(line_entry)

    shot_beats = {}
    for beat_id, shot_id in beat_shot_pairs:
        shot_beats.setdefault(shot_id, [])
        if beat_id not in shot_beats[shot_id]:
            shot_beats[shot_id].append(beat_id)
    for b in beats:
        if not any(b["id"] in b_list for b_list in shot_beats.values()):
            first_shot = next(iter(shot_beats), "SHOT-001")
            shot_beats.setdefault(first_shot, []).append(b["id"])

    beat_by_id = {b["id"]: b for b in beats}
    referenced_prompts = sorted(i for i in referenced if i.startswith("PROMPT-"))
    space_prompts = [p for p in referenced_prompts if "SPACE" in p]
    board_prompts = [p for p in referenced_prompts if "BOARD" in p]
    video_prompts = [p for p in referenced_prompts if "VIDEO" in p]

    prompts = []
    global_static_ids = []
    for sp_id in space_prompts:
        global_static_ids.append(sp_id)
        prompts.append({
            "id": sp_id,
            "revision": 1,
            "template": "T5",
            "shot_id": None,
            "duration": None,
            "asset_ids": [default_scene_id],
            "reference_bindings": [{"slot": "@图片1", "asset_id": default_scene_id}],
            "text": (
                f"@图片1 参考场景{scene_map[default_scene_id]}的空间布局，色彩光影与画面风格。禁止继承构图，景别。\n"
                f"生成一张三行三列的九视角场景空间参考图，画面纯净无人物，无文字标注。\n"
                f"{scene_map[default_scene_id]}空间结构完整，定锚物位置固定。\n"
                f"写实材质，基础漫射光，三行三列等大满幅网格，不添加底部文字条。\n"
                f"九个视角的墙体与地面连续闭合，定锚物位置跨视角一致。\n"
                f"--ar {aspect_ratio}"
            ),
            "depends_on": [],
        })

    shots = []
    for s_idx, (shot_id, b_ids) in enumerate(shot_beats.items(), 1):
        s_scenes = list(dict.fromkeys(beat_by_id[b]["scene_id"] for b in b_ids))
        s_chars = list(dict.fromkeys(c for b in b_ids for c in beat_by_id[b]["character_ids"]))
        s_props = list(dict.fromkeys(p for b in b_ids for p in beat_by_id[b]["prop_ids"]))
        s_lines = [
            {"dialogue_id": d["id"], "text": d["text"]}
            for d in dialogues
            if d["beat_id"] in b_ids
        ]
        board_id = board_prompts[s_idx - 1] if s_idx - 1 < len(board_prompts) else f"PROMPT-BOARD-{s_idx:03d}"
        video_id = video_prompts[s_idx - 1] if s_idx - 1 < len(video_prompts) else f"PROMPT-VIDEO-{s_idx:03d}"

        board_cells = "\n".join(
            f"Shot #{cell_i}（{(cell_i - 1) * 0.5:.1f}秒节点·物理镜头1）：{shot_id}第{cell_i}格关键帧构图与动作状态。"
            for cell_i in range(1, 9)
        ) + f"\nShot #9（5.0秒切出末态·物理镜头1）：{shot_id}第9格结束末态。"
        prompts.append({
            "id": board_id,
            "revision": 1,
            "template": "T6B",
            "shot_id": shot_id,
            "duration": None,
            "asset_ids": s_chars + s_scenes + s_props,
            "reference_bindings": [],
            "text": (
                f"生成一张三行三列等大满幅的专业影视黑白线稿关键帧故事板，白底黑线与三阶灰，整体与单格画幅均为{aspect_ratio}，画面内无信息栏，无左栏调度图，无文字与编号标签。\n"
                f"整体情绪为克制推进，九格按时间顺序定格。\n"
                f"{board_cells}\n"
                f"九格人物与空间定锚物位置连贯，画面保持黑白灰，全图无文字。\n"
                f"--ar {aspect_ratio}"
            ),
            "depends_on": [],
        })

        spoken_clauses = " ".join(f'说：“{line["text"]}”' for line in s_lines)
        action_summary = "；".join(beat_by_id[b]["summary"] for b in b_ids)
        prompts.append({
            "id": video_id,
            "revision": 1,
            "template": "T9",
            "shot_id": shot_id,
            "duration": 5.0,
            "asset_ids": s_chars + s_scenes + s_props,
            "reference_bindings": [],
            "text": (
                f"生成一段单镜头5秒的剧情短片，同步生成环境音，音效，配音与背景音乐，音画口型同步。画面纯净，无字幕。\n"
                f"整体情绪为平稳推进，从起幅动作到落幅收束。\n"
                f"写实影视画面风格，柔和自然光影，色彩层次清晰，材质纹理细腻。\n"
                f"环境音：持续铺设环境底噪。\n"
                f"BGM：低音弦乐铺底。\n"
                f"镜头1（0.0-5.0s）：平视中近景，{action_summary} {spoken_clauses}\n"
                f"人物与道具接触关系清晰，空间边界稳定连续，袖口贴合手腕。\n"
                f"--ar {aspect_ratio}"
            ),
            "depends_on": [],
        })

        shots.append({
            "id": shot_id,
            "revision": 1,
            "title": f"分镜{s_idx}",
            "scene_ids": s_scenes,
            "character_ids": s_chars,
            "prop_ids": s_props,
            "beat_ids": b_ids,
            "duration": 5.0,
            "segments": [
                {
                    "index": 1,
                    "start": 0.0,
                    "end": 5.0,
                    "description": action_summary,
                    "lines": s_lines,
                }
            ],
            "static_prompt_ids": global_static_ids + [board_id],
            "dynamic_prompt_id": video_id,
            "design": [
                {
                    "role": role,
                    "knowledge": f"{role}岗位设计依据。",
                    "decision": f"{shot_id} {role}岗位执行决策：{action_summary}",
                }
                for role in DESIGN_ROLES
            ],
            "audio": {
                "ambience": "环境底噪持续。",
                "music": "低音弦乐轻铺。",
                "effects": [],
            },
            "depends_on": [],
            "function": action_summary,
            "transitions": {
                "incoming": "承接上一状态入画。",
                "outgoing": "保持落幅末态切出。",
            },
            "review": {
                "design_id": f"9B-{shot_id}",
                "status": "unreviewed",
            },
            "notes": "由 extract-script --scaffold 自动生成的项目骨架草稿，待补充八岗位细节与精修提示词。",
        })

    draft = {
        "schema_version": "1.0",
        "project": {
            "id": project_id,
            "revision": 1,
            "title": title,
            "aspect_ratio": aspect_ratio,
            "style": "写实短剧风格，自然光影。",
        },
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "beats": beats,
        "dialogues": dialogues,
        "shots": shots,
        "prompts": prompts,
    }
    return snapshot_dependencies(draft)


def _write_json(data, target_path, in_place=False):
    payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output = Path(target_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not in_place:
        with output.open("xb") as handle:
            handle.write(payload)
        return output
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=output.parent,
                                         prefix=f".{output.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
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

    sync_parser = sub.add_parser("sync-assets", help="从共享资产库或上游项目同步角色、场景、道具、声音及全局静态提示词")
    sync_parser.add_argument("project")
    sync_parser.add_argument("--from", dest="shared", required=True, help="共享资产 JSON 或上游 project.json")
    sync_parser.add_argument("--include-new", action="store_true", help="同时并入当前项目尚未收录的新共享资产")
    sync_out = sync_parser.add_mutually_exclusive_group(required=True)
    sync_out.add_argument("--output", help="输出新文件路径（不得覆盖已有文件）")
    sync_out.add_argument("-i", "--in-place", action="store_true", help="原地更新输入 JSON 文件")

    extract_parser = sub.add_parser("extract-script", help="从源剧本或前期交接 Markdown 提取动作与台词结构")
    extract_parser.add_argument("source", help="源剧本或交接 Markdown 文件路径")
    extract_parser.add_argument("--scaffold", action="store_true", help="生成可通过完整 Schema 与源剧本对账的 project.json 初始骨架草稿")
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
            if args.scaffold:
                payload = scaffold_project_from_source(source_text)
            else:
                parsed = parse_source_script(source_text)
                if parsed["errors"]:
                    raise ValueError("\n".join(parsed["errors"]))
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
