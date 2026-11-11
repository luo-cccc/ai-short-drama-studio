#!/usr/bin/env python3
"""Render validated project JSON into project and five-chapter shot Markdown."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

try:
    from .project_data import DESIGN_ROLES, entity_fingerprint, entity_index, load_project
except ImportError:
    from project_data import DESIGN_ROLES, entity_fingerprint, entity_index, load_project

ROLE_NAMES = dict(zip(DESIGN_ROLES, (
    "总导演·叙事", "摄影导演·镜头", "光影导演·光", "动作指导·表演",
    "空间调度·站位纵深", "台词编辑·语言", "音频师·声场", "特效师·视觉特效")))


def prose(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace(chr(96), "ˋ")


def cell(value):
    return prose(value).replace("|", r"\|").replace("<", "&lt;").replace(">", "&gt;")


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(map(cell, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(cell(item) for item in row) + " |" for row in rows],
    ])


def prompt_block(prompt):
    metadata = f"<!-- prompt id={prompt['id']} template={prompt['template']}"
    if prompt["duration"] is not None:
        metadata += f" duration={prompt['duration']:.1f}"
    metadata += " -->"
    runs = [len(match.group()) for match in re.finditer(chr(96) + "+", prompt["text"])]
    fence = chr(96) * max(3, max(runs, default=0) + 1)
    return f"{metadata}\n{fence}text\n{prompt['text'].rstrip()}\n{fence}"


def render_documents(data):
    try:
        from .qc_check import check_project
    except ImportError:
        from qc_check import check_project
    results = check_project(data)
    errors = [f"{result.get('prompt_id') or 'project'}: {error}"
              for result in results for error in result["errors"]]
    if errors:
        raise ValueError("\n".join(errors))
    index = entity_index(data)
    project = data["project"]
    global_lines = [f"# {prose(project['title'])} · 制作方案",
                    "\n## 项目全局设定\n",
                    table(["项目 ID", "版本", "画幅", "风格"],
                          [[project["id"], project["revision"], project["aspect_ratio"], project["style"]]])]
    for title, name in (("角色", "characters"), ("场景", "scenes"), ("道具", "props")):
        global_lines.extend([f"\n### {title}\n",
                             table(["ID", "名称", "视觉设定"],
                                   [[e["id"], e["name"], e["description"]] for e in data[name]])])
    global_lines.append("\n## 剧本节拍与原始台词\n")
    for beat in data["beats"]:
        global_lines.extend([f"### {beat['id']} · {prose(index[beat['scene_id']]['name'])}\n",
                             prose(beat["summary"])])
        for line in data["dialogues"]:
            if line["beat_id"] == beat["id"]:
                speaker = index[line["speaker_id"]]["name"] if line["speaker_id"] else "旁白"
                global_lines.append(f"\n{line['id']} · {prose(speaker)}：{prose(line['text'])}")
    global_lines.extend(["\n## 静态资产总库\n"])
    for prompt in data["prompts"]:
        if prompt["shot_id"] is None:
            global_lines.extend([f"### {prompt['id']} · {prompt['template']}\n", prompt_block(prompt)])
    review_names = {"unreviewed": "未审查", "needs_revision": "需修订", "approved": "通过"}
    rows = []
    for shot in data["shots"]:
        designs = {item["role"]: item["decision"] for item in shot["design"]}
        rows.append([
            shot["id"], f"{shot['duration']:.1f}s", shot["function"],
            "；".join(index[beat]["summary"] for beat in shot["beat_ids"]),
            len(shot["segments"]),
            " → ".join(f"{s['end'] - s['start']:.1f}s" for s in shot["segments"]),
            designs["camera"], designs["lighting"],
            "；".join(shot["audio"]["effects"]) or shot["audio"]["ambience"],
            f"入场：{shot['transitions']['incoming']}；出场：{shot['transitions']['outgoing']}",
            "；".join(line["text"] for segment in shot["segments"] for line in segment["lines"]),
            "；".join(f"{binding['slot']}→{binding['asset_id']}"
                     for prompt_id in shot["static_prompt_ids"] + [shot["dynamic_prompt_id"]]
                     for binding in index[prompt_id]["reference_bindings"]),
            shot["review"]["design_id"], review_names[shot["review"]["status"]], shot["notes"],
        ])
    global_lines.extend(["\n## 总分镜表\n",
                         table(["镜号", "合规时长档位", "分镜核心功能", "核心剧情梗概",
                                "分镜头数量", "切镜节奏", "核心镜头语言设计", "核心光影基调",
                                "关键音频节点", "转场设计", "核心配音台词内容", "参考图资产",
                                "9B设计编号", "9B-1B审查状态", "备注"], rows)])
    documents = {"project.md": "\n\n".join(global_lines).rstrip() + "\n"}
    for shot in data["shots"]:
        lines = [f"# {shot['id']} · {prose(shot['title'])}",
                 "\n## 第一章 · 分镜设计思维\n"]
        for role in DESIGN_ROLES:
            design = next(item for item in shot["design"] if item["role"] == role)
            lines.extend([f"### {ROLE_NAMES[role]}\n",
                          f"专业知识：{prose(design['knowledge'])}\n",
                          f"本镜决策：{prose(design['decision'])}"])
        lines.append("\n## 第二章 · 静态资产描述词\n")
        for prompt_id in shot["static_prompt_ids"]:
            prompt = index[prompt_id]
            if prompt["shot_id"] is None:
                lines.append(f"空间图复用声明：复用 {prompt_id}，见 project.md 静态资产总库。")
            else:
                lines.extend([f"### {prompt_id} · {prompt['template']}\n", prompt_block(prompt)])
        lines.extend(["\n## 第三章 · 动态视频描述词\n",
                      prompt_block(index[shot["dynamic_prompt_id"]]),
                      "\n## 第四章 · 配音与音效脚本\n",
                      "### 声线设定\n",
                      table(["角色 ID", "角色", "声线"],
                            [[index[c]["id"], index[c]["name"], index[c]["voice"]]
                             for c in shot["character_ids"]]),
                      "\n### 人声配音\n"])
        deliveries = []
        for segment in shot["segments"]:
            for delivery in segment["lines"]:
                source = index[delivery["dialogue_id"]]
                speaker = index[source["speaker_id"]]["name"] if source["speaker_id"] else "旁白"
                deliveries.append([source["id"], segment["index"],
                                   f"{segment['start']:.1f}–{segment['end']:.1f}s",
                                   speaker, source["kind"], delivery["text"]])
        lines.extend([table(["台词 ID", "镜头", "区间", "角色", "类型", "原文"], deliveries),
                      "\n### 音效与 BGM\n",
                      table(["类别", "描述"], [["环境音", shot["audio"]["ambience"]],
                                             ["BGM", shot["audio"]["music"]],
                                             *[["音效", effect] for effect in shot["audio"]["effects"]]]),
                      "\n## 第五章 · 素材位对照与资产清单\n"])
        bindings = []
        for prompt_id in shot["static_prompt_ids"] + [shot["dynamic_prompt_id"]]:
            for binding in index[prompt_id]["reference_bindings"]:
                asset = index[binding["asset_id"]]
                bindings.append([prompt_id, binding["slot"], binding["asset_id"],
                                 asset.get("name", asset.get("template", ""))])
        lines.extend([table(["生成块", "素材位", "资产 ID", "内容"], bindings),
                      "\n" + table(["资产 ID", "名称", "制作状态"],
                                   [[asset_id, index[asset_id]["name"], "已定义；生成状态需人工确认"]
                                    for asset_id in shot["character_ids"] + shot["scene_ids"] + shot["prop_ids"]])])
        documents[f"{shot['id']}_分镜.md"] = "\n\n".join(lines).rstrip() + "\n"
    if len({name.casefold() for name in documents}) != len(documents):
        raise ValueError("分镜 ID 在 Windows 文件名中大小写冲突")
    return documents


def export_project(data, output):
    documents = render_documents(data)
    output = Path(output)
    manifest_path = output / ".drama-export.json"
    old_files = {}
    if manifest_path.exists():
        manifest = load_project(manifest_path)
        if manifest.get("project_id") != data["project"]["id"]:
            raise ValueError("导出目录已属于另一项目")
        old_files = manifest.get("files", {})
        if not isinstance(old_files, dict):
            raise ValueError("导出清单 files 非法")
    for name in documents:
        target = output / name
        if target.exists():
            if name not in old_files:
                raise ValueError(f"目标含非托管文件，拒绝覆盖：{target}")
            actual = entity_fingerprint({"text": target.read_text(encoding="utf-8")})
            if actual != old_files[name]:
                raise ValueError(f"交付文件被手工修改，先合并回 JSON 或使用新目录：{target}")
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, text in documents.items():
        (output / name).write_text(text, encoding="utf-8", newline="\n")
        files[name] = entity_fingerprint({"text": text})
    obsolete = sorted(set(old_files) - set(documents))
    manifest_path.write_text(json.dumps({
        "project_id": data["project"]["id"], "project_fingerprint": entity_fingerprint(data["project"]),
        "files": files, "obsolete_files": obsolete,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [output / name for name in documents], obsolete


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        paths, obsolete = export_project(load_project(args.project), args.output)
        for path in paths:
            print(path)
        if obsolete:
            print("WARN: 旧交付文件仍保留，请人工处理：" + ", ".join(obsolete))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
