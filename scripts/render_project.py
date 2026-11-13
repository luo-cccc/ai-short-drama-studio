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


def build_wan_visual_prompt(prompt_text: str, voice_slots=()) -> str:
    """将 T7–T9 全模态动态提示词转换为适配万相 Wan（I2V / FLF2V 首尾帧）的纯视觉提示词。

    剥离 @素材 声明、环境音/BGM 行与引号内台词文本，提供纯视觉兼容草稿；
    局部镜头尽量移除不可见五官词，最终仍需核对动作、构图及实际模型输出。
    """
    # 先把合法的跨行对白合为一行，避免逐行处理留下半句原文或引号。
    prompt_text = re.sub(r'“[^”]*”', lambda match: match.group().replace("\n", " "), prompt_text)
    prompt_text = re.sub(r'([：:])[ \t]*\n[ \t]*(?=[“"])', r'\1', prompt_text)
    continuation = re.compile(
        r"^(?:禁止\s*继承|只取|不取|不继承|不参考|不包含|不采纳|禁止参考|排除|不使用|"
        r"(?:并|同时|继续)?(?:继承|参考|采用|沿用|保留))"
    )
    voice_slot_pattern = "|".join(re.escape(slot) + r"(?!\d)" for slot in voice_slots)
    def has_visible_face(body):
        body = re.sub(r'“[^”]*”|"[^"\n]*"', "", body)
        body = re.sub(r"(?:不露|未露|看不到|不显示|不出现)[^，。；\n]{0,8}(?:面部|脸部|正脸|侧脸|五官|嘴部|脸)|(?:面部|脸部|五官|嘴部)不入画", "", body)
        return bool(re.search(r"脸|面部|面庞|眼|眉|瞳|唇|嘴|头顶|全身|中景|中近景|全景|远景", body))

    shot_rows = list(re.finditer(r"(?m)^[ \t]*镜头[1-9]\d*[（(]", prompt_text))
    visibility = [has_visible_face(prompt_text[row.start():shot_rows[number + 1].start() if number + 1 < len(shot_rows) else len(prompt_text)])
                  for number, row in enumerate(shot_rows)]
    face_visible = any(visibility) if visibility else has_visible_face(prompt_text)
    current_face_visible, shot_index = face_visible, -1
    face_clause_re = re.compile(r"窄脸|圆脸|方脸|瓜子脸|鹅蛋脸|五官|眉|瞳孔|眼|鼻|唇")

    out_lines: list[str] = []
    skip_cont = False
    for raw_line in prompt_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if re.match(r"^@(?:素材|图片)\d+\s+参考", stripped):
            skip_cont = True
            continue
        if skip_cont and continuation.match(stripped):
            continue
        skip_cont = False
        if stripped.startswith(("环境音：", "环境音:", "BGM：", "BGM:")):
            continue
        if re.match(r"^镜头[1-9]\d*[（(]", stripped):
            shot_index += 1
            current_face_visible = visibility[shot_index] if shot_index < len(visibility) else False
        line = stripped
        if voice_slot_pattern:
            # 声音参考的用途说明不进入纯视觉降级块；角色外观行只移除音频引用子句。
            if re.match(r"^(?:声音|音色|音频|声线)(?:参考|身份|绑定|说明|[：:])", line) and re.search(voice_slot_pattern, line):
                continue
            line = re.sub(r"(?:声音身份|声音|音色|声线)(?:参考|绑定)[ \t]*(?:" + voice_slot_pattern + r")[，,、;；]?[ \t]*", "", line)
        # 转换任务头：去除音频与口型同步指令，强调首尾帧连续纯视觉
        mouth_visible = current_face_visible and not re.search(r"画外|\bOS\b|\bNAR\b|旁白|内心独白", line)
        line = re.sub(
            r"，?同步生成[^。\n]*?音画口型同步。",
            "，纯视觉画面生成，首尾帧动作与光影自然过渡。",
            line,
        )
        # 去除主体/场景行中的 @素材 引用标记
        line = re.sub(r"参考@(?:素材|图片)\d+(?:@(?:素材|图片)\d+)*[，,、\s]*", "", line)
        # 若全程不露脸，过滤角色行中的五官特征子句，防止万相强行扭头或拉远露脸
        if not face_visible and line.startswith("角色") and "：" in line:
            prefix, rest = line.split("：", 1)
            body_text = rest.rstrip("。")
            kept = [c.strip() for c in re.split(r"[，,、]", body_text) if c.strip() and not face_clause_re.search(c)]
            if kept:
                line = f"{prefix}：{'，'.join(kept)}。"
        # 将画外音/OS/NAR带引号句子移除，将角色台词（含声线/语速修饰）转换为纯视觉口型动作描述
        line = re.sub(
            r"(?:OS|NAR|旁白|内心独白|画外音)[^。；;\n]*?[“\"][^”\"]*[”\"][。；;，,]?",
            "",
            line,
        )
        line = re.sub(
            r"(?:(?:以|用)[^，。；;\n]*?(?:音|声线|语气|声音|腔调)[^：:\n]{0,25}?)?"
            r"(?:(?:压低声音|放低声音|提高声音|急促|快速|匀速|平缓|缓慢|凝滞|克制|冷静|低声|轻声|沉声|柔声|冷冷|缓缓|短句)[^：:\n]{0,15}?)?"
            r"(?:说|说道|说出|问|问道|询问|答|回答|喊|喊道|念|道|开口|开口道|收尾|低语|轻声说|沉声说|耳语|吟诵|喝道|吼道|喃喃|喃喃道)[：:]\s*[“\"][^”\"]*[”\"]",
            "嘴唇自然开合完成说话动作。" if mouth_visible else "",
            line,
        )
        line = re.sub(r"(?:她的|他的|其)?声音在画外继续[。；;，,\s]*", "", line)
        line = re.sub(r"话音落后[，,]?", "", line)
        line = re.sub(r"[“\"][^”\"]*[”\"]", "", line)
        line = re.sub(r"[，,、；;]+[。]", "。", line)
        line = re.sub(r"。+", "。", line)
        line = re.sub(r"[，,]{2,}", "，", line).strip("，,、；; ")
        if line and line not in {"她", "他", "它", "她以", "他以", "它以", "她用", "他用", "它用"}:
            out_lines.append(line)
    return "\n".join(out_lines)


def wan_prompt_block(prompt):
    voice_slots = [binding["slot"] for binding in prompt["reference_bindings"]
                   if binding["asset_id"].startswith("VOICE-")]
    wan_text = build_wan_visual_prompt(prompt["text"], voice_slots)
    runs = [len(match.group()) for match in re.finditer(chr(96) + "+", wan_text)]
    fence = chr(96) * max(3, max(runs, default=0) + 1)
    return f"{fence}wan\n{wan_text.rstrip()}\n{fence}"


def prompt_block(prompt):
    metadata = f"<!-- prompt id={prompt['id']} template={prompt['template']}"
    if prompt["duration"] is not None:
        metadata += f" duration={prompt['duration']:.1f}"
    metadata += " -->"
    runs = [len(match.group()) for match in re.finditer(chr(96) + "+", prompt["text"])]
    fence = chr(96) * max(3, max(runs, default=0) + 1)
    return f"{metadata}\n{fence}text\n{prompt['text'].rstrip()}\n{fence}"


def voice_state(voice):
    status = {"planned": "待制作；不可投喂", "ready": "已有音频"}[voice["status"]]
    audition = {"unreviewed": "未试听", "approved": "试听通过", "needs_revision": "需修订"}[voice["audition"]]
    return f"{status}；{audition}"


def voice_owner(voice, index):
    return index[voice["character_id"]]["name"] if voice["character_id"] else "旁白"


def voice_card(voice, index):
    """声音转写只作资产资料展示，不写入正式对白或提示词代码块。"""
    lines = [f"### {voice['id']} · {prose(voice['name'])}\n",
             table(["角色", "版本", "语言", "制作与试听状态"],
                   [[voice_owner(voice, index), voice["revision"], voice["language"], voice_state(voice)]]),
             f"声音设计：{prose(voice['description'])}\n",
             f"来源：{prose(voice['source'])}"]
    if voice["status"] == "planned":
        lines.append("试听制作说明：按上述声音设计与语言制作单人常态说话样片，试听定版后登记母版和模型投喂副本；当前不分配上传槽位。")
    if voice.get("audition_text"):
        lines.append(f"试听文案（用于制作参考音频，不是剧情对白）：{prose(voice['audition_text'])}")
    master = voice["master"]
    if master is not None:
        lines.extend(["\n母版资料（转写仅用于核对参考内容，不是本镜对白）：\n",
                      table(["文件", "时长", "SHA-256", "参考转写"],
                            [[master["path"], f"{master['duration']:.3f}s", master["sha256"], master["transcript"]]])])
    if voice["references"]:
        lines.extend(["\n模型投喂副本：\n",
                      table(["副本 ID", "目标模型", "文件", "时长", "母版取用区间", "SHA-256", "参考转写"],
                            [[reference["id"], reference["model_id"], reference["path"],
                              f"{reference['duration']:.3f}s",
                              f"{reference['source_start']:.3f}–{reference['source_end']:.3f}s",
                              reference["sha256"], reference["transcript"]]
                             for reference in voice["references"]])])
    if voice["notes"]:
        lines.append(f"备注：{prose(voice['notes'])}")
    return "\n\n".join(lines)


def shot_voices(data, shot, index):
    prompt = index[shot["dynamic_prompt_id"]]
    bound = {binding["asset_id"] for binding in prompt["reference_bindings"]
             if binding["asset_id"].startswith("VOICE-")}
    speakers = {index[line["dialogue_id"]]["speaker_id"]
                for segment in shot["segments"] for line in segment["lines"]}
    bound_owners = {index[voice_id]["character_id"] for voice_id in bound}
    return [voice for voice in data.get("voices", [])
            if voice["id"] in bound or (voice["character_id"] in speakers and voice["character_id"] not in bound_owners)]


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
    if data.get("voices"):
        global_lines.extend(["\n## 角色声音参考资产库\n",
                             "声音样片用于视频模型的角色声音身份参考；正式台词和本镜表演以分镜正文为准。文件路径相对于项目媒体根目录，导出不复制音频。"])
        global_lines.extend(voice_card(voice, index) for voice in data["voices"])
    global_lines.append("\n## 剧本节拍与原始台词\n")
    for beat in data["beats"]:
        global_lines.extend([f"### {beat['id']} · {prose(index[beat['scene_id']]['name'])}\n",
                             prose(beat["summary"])])
    global_lines.extend(["\n### 原始台词（执行顺序）\n",
                         table(["台词 ID", "节拍 ID", "角色", "类型", "原文"], [
                             [line["id"], line["beat_id"],
                              index[line["speaker_id"]]["name"] if line["speaker_id"] else "旁白",
                              line["kind"], line["text"]]
                             for line in data["dialogues"]])])
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
                                "关键音频节点", "转场设计", "核心配音台词内容", "参考素材资产",
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
        dynamic = index[shot["dynamic_prompt_id"]]
        profile = dynamic.get("audio_reference_profile")
        lines.append("\n## 第三章 · 动态视频描述词\n")
        if profile is not None:
            lines.extend([f"### {prose(profile['model_id'])} · 目标模型动态提示词\n",
                          "声音参考以第五章实际列出的音频槽为准；未列槽位不上传。参考样片用于声音身份，本镜表演与正式台词沿用下方正文。" if profile["supports_voice_reference"] else
                          "该模型配置不支持角色声音参考；本块不提供音频上传槽，声音描述仍是生成目标。",
                          prompt_block(dynamic)])
        else:
            lines.extend(["### 即梦 Seedance 全模态版（多素材参考 + 音画同步）\n",
                          prompt_block(dynamic),
                          "\n### 万相 Wan 纯视觉首尾帧适配版（I2V / FLF2V）\n",
                          "首尾帧与切图投喂说明：只有与目标成片外观一致、对应本镜实际起终态的时序故事板单帧或已验收成片帧，才作为首尾帧候选。T5空间九视角仅作机位参考；T6B线稿用于结构参考，写实或彩色制作应先生成匹配目标外观的单帧。`Shot_01.png`/`Shot_09.png`是时序板切片的文件名，不代表已验证可直接投喂。下方为已移除台词和主要音频指令的纯视觉兼容草稿，使用前核对动作、构图与实际接口：\n",
                          wan_prompt_block(dynamic)])
        voices = shot_voices(data, shot, index)
        lines.extend(["\n## 第四章 · 配音与音效脚本\n",
                      "### 声线设定\n",
                      table(["角色 ID", "角色", "声线"],
                            [[index[c]["id"], index[c]["name"], index[c]["voice"]]
                             for c in shot["character_ids"]])])
        if voices:
            bound_voice_ids = {binding["asset_id"] for binding in dynamic["reference_bindings"]
                               if binding["asset_id"].startswith("VOICE-")}
            lines.extend(["\n### 角色声音参考与本镜表演\n",
                          table(["声音 ID", "角色", "声音身份", "状态", "本镜引用"],
                                [[voice["id"], voice_owner(voice, index), voice["description"], voice_state(voice),
                                  "已绑定；见第五章" if voice["id"] in bound_voice_ids else "未绑定；不上传"]
                                 for voice in voices]),
                          "声音参考只用于音色、口音与咬字等身份特征。本镜情绪、语速、重音、停顿及台词由动态正文执行；样片转写不作为正式对白。",
                          "本镜声音执行：" + prose(next(item["decision"] for item in shot["design"] if item["role"] == "dialogue")),
                          "\n### 视频正式对白与计划时段\n"])
        else:
            lines.append("\n### 人声配音\n")
        deliveries = []
        for segment in shot["segments"]:
            for delivery in segment["lines"]:
                source = index[delivery["dialogue_id"]]
                speaker = index[source["speaker_id"]]["name"] if source["speaker_id"] else "旁白"
                cue = (f"{delivery['start']:.1f}–{delivery['end']:.1f}s"
                       if "start" in delivery and "end" in delivery else "未标定")
                deliveries.append([source["id"], segment["index"],
                                   f"{segment['start']:.1f}–{segment['end']:.1f}s",
                                   cue, speaker, source["kind"], delivery["text"]])
        lines.extend([table(["台词 ID", "起始镜头", "所属镜头区间", "发声区间（片段局部）",
                             "角色", "类型", "原文"], deliveries),
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
        lines.append(table(["生成块", "素材位", "资产 ID", "内容"], bindings))
        voice_bindings = [binding for binding in dynamic["reference_bindings"]
                          if binding["asset_id"].startswith("VOICE-")]
        if profile is not None:
            limit = lambda value, suffix="": "未登记；按目标模型核对" if value is None else f"{value}{suffix}"
            lines.extend(["\n### 声音参考模型配置\n",
                          table(["目标模型", "支持音色参考", "文件数上限", "单文件时长上限", "总时长上限", "格式", "能力依据"],
                                [[profile["model_id"], "是" if profile["supports_voice_reference"] else "否",
                                  limit(profile["max_files"]), limit(profile["max_file_duration"], "s"),
                                  limit(profile["max_total_duration"], "s"),
                                  "、".join(profile["formats"]) or "未登记；按目标模型核对", profile["source"]]])])
        if voice_bindings:
            voice_rows = []
            for binding in voice_bindings:
                voice = index[binding["asset_id"]]
                reference = next(item for item in voice["references"]
                                 if item["id"] == binding["audio_reference_id"])
                voice_rows.append([binding["slot"], voice["id"], voice_owner(voice, index), reference["model_id"],
                                   reference["id"], reference["path"], f"{reference['duration']:.3f}s",
                                   f"{reference['source_start']:.3f}–{reference['source_end']:.3f}s", reference["sha256"]])
            lines.extend(["\n### 本镜音频上传槽\n",
                          table(["素材位", "声音 ID", "角色", "目标模型", "副本 ID", "音频文件", "时长", "母版取用区间", "SHA-256"], voice_rows),
                          "按表逐一将文件绑定对应角色；样片中的文字、情绪和背景声不作为本镜生成内容。返片核对角色归属、正式台词、样片串读及跨镜声音一致性。"])
        elif voices:
            lines.append("\n本镜没有已绑定的声音参考文件；待制作或未绑定声音不占上传槽位。")
        lines.extend([
                      "\n" + table(["资产 ID", "名称", "制作状态"],
                                   [[asset_id, index[asset_id]["name"], "已定义；生成状态需人工确认"]
                                    for asset_id in shot["character_ids"] + shot["scene_ids"] + shot["prop_ids"]])])
        if shot.get("overlays"):
            overlay_kinds = {
                "in_scene": "画内文字",
                "post_subtitle": "后期字幕",
                "post_ui": "后期UI/面板",
                "post_graphic": "后期花字/贴片",
            }
            overlay_rows = [
                [
                    overlay_kinds.get(ov["kind"], ov["kind"]),
                    f"{ov['start']:.1f}–{ov['end']:.1f}s" if "start" in ov and "end" in ov else "全镜/未标定",
                    ov.get("position", "未指定"),
                    ov["method"],
                    ov["text"],
                ]
                for ov in shot["overlays"]
            ]
            lines.extend([
                "\n### 画内文字与后期叠字\n",
                table(["类别", "区间（片段局部）", "位置/载体", "实现方式", "文案内容"], overlay_rows),
            ])
        documents[f"{shot['id']}_分镜.md"] = "\n\n".join(lines).rstrip() + "\n"
    if len({name.casefold() for name in documents}) != len(documents):
        raise ValueError("分镜 ID 在 Windows 文件名中大小写冲突")
    return documents


def export_project(data, output, *, media_root=None):
    documents = render_documents(data)
    # 完整编码成功后才触碰交付目录，避免非法Unicode在写到一半时损坏已有交付。
    payloads = {name: content.encode("utf-8") for name, content in documents.items()}
    if media_root is not None:
        try:
            from .project_data import validate_voice_media
        except ImportError:
            from project_data import validate_voice_media
        errors, _ = validate_voice_media(data, media_root)
        if errors:
            raise ValueError("\n".join(errors))
    output = Path(output)
    manifest_path = output / ".drama-export.json"
    old_files = {}
    old_obsolete = []
    old_obsolete_fingerprints = {}
    if manifest_path.exists():
        manifest = load_project(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("导出清单根节点必须是对象")
        if manifest.get("project_id") != data["project"]["id"]:
            raise ValueError("导出目录已属于另一项目")
        old_files = manifest.get("files", {})
        if not isinstance(old_files, dict):
            raise ValueError("导出清单 files 非法")
        old_obsolete = manifest.get("obsolete_files", [])
        if not isinstance(old_obsolete, list) or not all(isinstance(name, str) for name in old_obsolete):
            raise ValueError("导出清单 obsolete_files 非法")
        old_obsolete_fingerprints = manifest.get("obsolete_file_fingerprints", {})
        if not isinstance(old_obsolete_fingerprints, dict):
            raise ValueError("导出清单 obsolete_file_fingerprints 非法")
    managed_fingerprints = {**old_obsolete_fingerprints, **old_files}
    for name in documents:
        target = output / name
        if target.exists():
            if name not in managed_fingerprints:
                raise ValueError(f"目标含非托管文件，拒绝覆盖：{target}")
            actual = entity_fingerprint({"text": target.read_text(encoding="utf-8")})
            if actual != managed_fingerprints[name]:
                raise ValueError(f"交付文件被手工修改，先合并回 JSON 或使用新目录：{target}")
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, text in documents.items():
        (output / name).write_bytes(payloads[name])
        files[name] = entity_fingerprint({"text": text})
    obsolete_candidates = set(old_files) | set(old_obsolete) | set(old_obsolete_fingerprints)
    obsolete = sorted(name for name in obsolete_candidates - set(documents)
                      if (output / name).exists())
    obsolete_fingerprints = {name: managed_fingerprints[name] for name in obsolete
                             if name in managed_fingerprints}
    manifest_path.write_text(json.dumps({
        "project_id": data["project"]["id"], "project_fingerprint": entity_fingerprint(data["project"]),
        "files": files, "obsolete_files": obsolete,
        "obsolete_file_fingerprints": obsolete_fingerprints,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [output / name for name in documents], obsolete


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--output", required=True)
    parser.add_argument("--media-root", help="声音文件的媒体根目录；提供时在导出前核对文件和指纹")
    args = parser.parse_args(argv)
    try:
        paths, obsolete = export_project(load_project(args.project), args.output, media_root=args.media_root)
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
