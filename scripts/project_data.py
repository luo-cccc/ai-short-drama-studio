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


def _dependency_errors(data, index):
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
    return errors


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


def validate_project(data, previous=None):
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture", help="显式记录已重做实体的当前依赖")
    capture_parser.add_argument("project")
    capture_parser.add_argument("--entity", action="append", required=True)
    capture_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        data = snapshot_dependencies(load_project(args.project), args.entity)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        print(f"已记录依赖：{output}")
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
