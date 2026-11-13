#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐提示词与结构化项目 QC；仅使用 Python 标准库。

python scripts/qc_check.py output/ --mode auto
python scripts/qc_check.py project.json --previous previous.json --format json
python scripts/qc_check.py prompt.txt --mode dynamic --duration 10

退出码：0 无 ERROR（WARN 仍需人工复核），1 存在 ERROR，2 命令参数错误。
Markdown 只检查提示词代码块；代码块外的规划、标题和素材清单不参加文本 QC。
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys


DISALLOWED_PUNCT = {"、": "顿号", "～": "波浪号", "「": "方引号", "」": "方引号", "『": "方引号", "』": "方引号"}
ELLIPSIS_BAD_PATTERN = r"(?<!…)…(?!…)|\.\.\."
MECHANISM_LABELS = [
    "Layer A", "Layer B", "主风格DNA", "六层结构", "五层黄金结构", "Template", "模板",
    "镜头N块", "镜头块数", "切镜节奏", "起始画面", "收尾画面", "最终画面", "首帧", "尾帧",
    "锚定所有", "约束词：", "（必填", "（重要", "（强制", "本镜约束", "自动匹配约束词", "分镜编号", "资产类型",
]
ABSTRACT_EMOTION = ["紧张", "恐惧", "悲伤", "绝望", "愤怒", "惊讶", "激动", "冷漠", "厌恶", "疲惫", "怀念", "骄傲", "尴尬", "懊悔", "嫉妒", "疯狂", "压抑", "怅然", "期待", "坚定", "疑惑", "轻蔑", "欣慰", "不甘", "癫狂"]
PHYSICAL_UNITS = [r"\d+\s*m/s", r"\d+\s*kg", r"\d+\s*lux", r"\d+\s*dB", r"\d+\s*赫兹", r"光比\s*1[:：]", r"头身比", r"身高\s*\d", r"每秒\s*\d", r"\d+\s*cm", r"\d+\s*米", r"\d+\s*秒速", r"ISO\s*\d", r"快门"]
COMPASS_PATTERNS = [r"坐北朝南", r"坐南朝北", r"朝[南北东西]", r"[南北东西](?:墙|侧|面|边)", r"[东西][南北]角", r"画面[左右]侧?（[东南西北]）"]
SPEED_NONSTD_HINT = {"放缓": "平缓", "滞缓": "缓慢", "骤急速": "急促", "慵懒": "平缓", "徐徐": "缓慢", "迟缓": "缓慢", "飞快": "快速", "极快": "急促"}
TEMPLATE_RE = re.compile(r"(?:\bTemplate\s*|\bT|模板\s*)([1-9][BC]?)(?=$|[^A-Za-z0-9])", re.I)
SLOT_RE = re.compile(r"@(?:素材|图片)\d+")
STAMP_RE = re.compile(r"镜头([1-9]\d*)（((?:0|[1-9]\d*)\.\d)-((?:0|[1-9]\d*)\.\d)s）：")
QUOTED_RE = re.compile(r'“([^”]*)”|"([^"\n]*)"')
# 编号、占位编号和括号/冒号具有声明特征；“镜头继续推进”等是正文续行。
STAMP_ROW_RE = re.compile(
    r"(?m)^[ \t]*(镜头(?=[ \t]*(?:\d|[A-Za-z]+(?=[ \t（(:：]|$)|"
    r"第[ \t]*(?:\d+|[A-Za-z]+|[零〇一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+)[ \t]*(?=[（(:：]|$)|"
    r"[零〇一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+(?=[ \t（(:：]|$)|[（(:：]|$))[^\n]*)"
)


def strip_ar(text: str) -> str:
    return re.sub(r"--ar\s+[\w:：/x×\-]+", "", text)


def count_words(text: str) -> int:
    text = strip_ar(text)
    return len(re.findall(r"[\u4e00-\u9fff]", text)) + len(re.findall(r"[A-Za-z]+", text)) + len(re.findall(r"\d+(?:\.\d+)?", text))


def quoted_strings(text: str) -> list[str]:
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in QUOTED_RE.finditer(text)]


def clip_quoted(text: str) -> str:
    return "".join(quoted_strings(text))


def _management_body(text: str, mode: str) -> str:
    """豁免镜头行对白与有说话/OS/NAR引导的续行，说明中的引号仍受检。"""
    if mode != "dynamic":
        return text
    spoken = re.compile(
        r'(?:说|问|答|喊|念|道|开口|收尾|低语|轻声|沉声|冷笑|叹息|耳语|吟诵|喝|吼|喃喃|OS|NAR|旁白|独白|画外音|台词)[：:][ \t]*$',
        re.I,
    )
    line_states, in_shot = {}, False
    for row in re.finditer(r"(?m)^([^\n]*)", text):
        line = row.group(1)
        timestamp = bool(STAMP_RE.match(line.lstrip(" \t")))
        if timestamp:
            in_shot = True
        elif line.lstrip(" \t").startswith("--ar"):
            in_shot = False
        line_states[row.start()] = timestamp, in_shot

    def without_dialogue(match):
        line_start = text.rfind("\n", 0, match.start()) + 1
        timestamp, active = line_states[line_start]
        prefix = text[line_start:match.start()]
        return "" if timestamp or (active and spoken.search(prefix)) else match.group()

    # 与quoted_strings一致，中文引号内允许换行；豁免范围由开引号的位置决定。
    return re.sub(r'“[^”]*”|"[^"\n]*"', without_dialogue, text)


def _reference_declarations(text: str) -> list[tuple[str, str]]:
    """独立抽取参考声明；相邻协议续句可以另起行或隔空行。"""
    lines, declarations = text.splitlines(), []
    continuation = re.compile(
        r"^(?:禁止\s*继承|只取|不取|不继承|不参考|不包含|不采纳|禁止参考|排除|不使用|"
        r"(?:并|同时|继续)?(?:继承|参考|采用|沿用|保留))"
    )
    for index, line in enumerate(lines):
        match = re.match(r"^[ \t]*(@(?:素材|图片)\d+)[ \t]+参考[ \t]*([^\r\n]+)", line)
        if not match:
            continue
        slot, first = match.groups()
        parts = [first.strip()]
        for following in lines[index + 1:]:
            following = following.strip()
            if not following:
                continue
            if not continuation.match(following):
                break
            parts.append(following)
        declarations.append((slot, "\n".join(parts)))
    return declarations


def _reference_scope(declaration: str) -> tuple[bool, str, set[str]]:
    """按声明主语识别场景参考，分离正向描述与明确禁止项。"""
    positive, raw_positive, excluded = [], [], set()
    negative_start = re.compile(r"^(?:禁止\s*继承|不取|不继承|不参考|不包含|不采纳|禁止参考|排除|不使用)")
    positive_start = re.compile(r"^(?:(?:并|同时|继续)?(?:继承|参考|采用|沿用|保留|只取|取)|但|却|然而|仍)")
    inline_exclusion = re.compile(r"除[^，。；;\n]*?(?:之外|以外|外)")
    for sentence in re.split(r"[。！？!?\n]", declaration):
        scope = "positive"
        for clause in re.split(r"[，；;]", sentence):
            clause = clause.strip()
            if not clause:
                continue
            if negative_start.match(clause):
                scope = "excluded" if re.match(r"^禁止\s*继承", clause) else "negative"
            elif positive_start.match(clause):
                scope = "positive"
            if scope == "excluded":
                excluded.update(word for word in ("画面风格", "光影", "色彩") if word in clause)
            elif scope == "positive":
                raw_positive.append(clause)
                positive.append(inline_exclusion.sub("", clause))
    subject = re.search(r"故事分镜图|故事板|调度图|场景|角色|人物|道具", raw_positive[0] if raw_positive else "")
    scene = bool(subject and subject.group() in {"场景", "故事板", "故事分镜图", "调度图"})
    return scene, "，".join(positive), excluded


def _is_voice_reference(declaration: str) -> bool:
    """声音身份声明不参加场景、外观或光影继承检查。"""
    positive = re.split(r"禁止\s*继承|不继承|不参考|不包含|不采纳|禁止参考|排除|不使用", declaration, maxsplit=1)[0]
    if re.match(r"\s*(?:场景|故事板|故事分镜图|调度图|道具)", positive):
        return False
    return bool(re.search(r"声音身份|音色|声线|人声|声音参考", positive))


def _template(text: str) -> str | None:
    match = TEMPLATE_RE.search(text)
    return "T" + match.group(1).upper() if match else None


def _mode(text: str, requested: str, template: str | None = None) -> str:
    if requested != "auto":
        return requested
    if isinstance(template, str) and template:
        return "dynamic" if template in {"T7", "T8", "T9"} else "static"
    return "dynamic" if re.search(r"(?m)^\s*镜头\d", text) or re.search(r"生成[^\n。]*?\d+(?:\.\d+)?\s*秒", text) else "static"


def _duration_in_text(text: str) -> Decimal | None:
    match = re.search(r"生成[^\n。]*?(\d+(?:\.\d+)?)\s*秒", text)
    return Decimal(match.group(1)) if match else None


def _check_t6b_references(text: str) -> tuple[list[str], list[str]]:
    """线稿参考只继承造型结构；明确排除句中的颜色词不算正向继承。"""
    errors, warnings = [], []
    attributes = re.compile(r"颜色|色彩|色调|配色|光影|光线|布光|色温|(?:画面|渲染|绘画|艺术|视觉|写实|动漫|动画|水墨|线稿)风格")
    negative_start = re.compile(r"^(?:不取|不继承|不参考|不包含|不采纳|禁止继承|禁止参考|排除|不使用)")
    uncertain_negative = re.compile(r"不|无|非|除|避免|禁止|舍弃")
    positive_followup = re.compile(r"^(?:并|同时|继续)?(?:继承|参考|采用|沿用|保留|只取|取)")
    for slot, declaration in _reference_declarations(text):
        sentences = re.split(r"[。！？!?\n]", declaration)
        for sentence_index, sentence in enumerate(sentences):
            for clause in re.split(r"[，；;]", sentence):
                clause = clause.strip()
                if not clause or not attributes.search(clause):
                    continue
                if negative_start.match(clause) and not re.search(r"但|却|然而|仍|同时", clause):
                    continue
                # 对复杂否定只提示复核，避免把“不取颜色、光影、渲染风格”判为继承。
                if uncertain_negative.search(clause):
                    warnings.append(f"{slot}T6B参考范围含复杂否定，请人工确认仅继承造型结构：「{clause}」")
                elif sentence_index == 0 or positive_followup.match(clause):
                    errors.append(f"{slot}T6B参考范围正向继承颜色、光影或画面风格：「{clause}」；线稿仅参考造型与空间结构")
                else:
                    warnings.append(f"{slot}T6B参考范围的后续说明含视觉风格属性，请人工核对：「{clause}」")
    return errors, warnings


def parse_timestamps(text: str, duration: float | None = None) -> tuple[list[dict], list[str]]:
    """严格解析每个镜头行；坏格式返回诊断，不尝试 float('...')。"""
    errors, stamps = [], []
    quoted_ranges = [match.span() for match in QUOTED_RE.finditer(text)]
    rows = [row for row in STAMP_ROW_RE.finditer(text)
            if not any(start <= row.start(1) < end for start, end in quoted_ranges)]
    if not rows:
        return [], ["动态描述词未检测到镜头时间戳：镜头N（0.0-5.0s）："]
    for row in rows:
        match = STAMP_RE.match(row.group(1))
        if not match:
            errors.append(f"时间戳格式非法：{row.group(1)[:65]}；须为镜头N（0.0-5.0s）：并保留一位小数")
            continue
        number, start, end = match.groups()
        stamps.append({"index": int(number), "start": Decimal(start), "end": Decimal(end), "offset": row.start(), "text_offset": row.start() + row.group(0).find(row.group(1)) + match.end()})
    if stamps:
        if [s["index"] for s in stamps] != list(range(1, len(stamps) + 1)):
            errors.append("镜头序号不连续，须从镜头1逐个递增")
        if stamps[0]["start"] != 0:
            errors.append("首个镜头必须从0.0秒开始")
        for i, stamp in enumerate(stamps):
            if stamp["end"] <= stamp["start"]:
                errors.append(f"镜头{stamp['index']}结束时间必须大于起始时间")
            if i and stamps[i - 1]["end"] != stamp["start"]:
                errors.append(f"镜头{stamp['index']}时间戳断裂或重叠：上一镜结束与本镜起始不一致")
        total = stamps[-1]["end"]
        if not Decimal("5") <= total <= Decimal("30"):
            errors.append(f"单条动态描述词总时长{total}s超出5–30秒范围")
        expected = _duration_in_text(text)
        if duration is not None:
            try:
                explicit = Decimal(str(duration))
                if not explicit.is_finite() or not Decimal("5") <= explicit <= Decimal("30"):
                    errors.append("规定时长须为5–30秒范围内的有限数值")
                elif expected is not None and explicit != expected:
                    errors.append(f"任务声明时长{expected}s与规定时长{explicit}s不一致")
                expected = explicit
            except (InvalidOperation, ValueError):
                errors.append("规定时长不是有效数值")
        if expected is not None and expected.is_finite() and total != expected:
            errors.append(f"总时长{total}s与规定时长{expected}s不一致")
    return stamps, errors


def check(text: str, mode: str = "dynamic", duration: float | None = 15, *, template: str | None = None) -> tuple[list[str], list[str]]:
    """检查一个纯提示词；兼容旧版 check(text, mode, duration) 接口。"""
    template = template if isinstance(template, str) else None
    mode = _mode(text, mode, template)
    errors, warns = [], []
    if not text.strip():
        return ["描述词为空"], []
    body, quoted = strip_ar(text), clip_quoted(text)
    management_body = _management_body(body, mode)
    layout = template in {"T5", "T6", "T6B"}
    for p, name in DISALLOWED_PUNCT.items():
        if p in quoted:
            errors.append(f"禁用标点「{p}」出现在台词/OS/NAR引号内（{name}）")
    if re.search(ELLIPSIS_BAD_PATTERN, quoted):
        errors.append("台词/OS/NAR须使用中文六点省略号……")
    non_ref_body = re.sub(r"(?m)^\s*@(?:素材|图片)\d+\s+参考[^\n]*", "", body)
    if "、" in non_ref_body and "、" not in quoted:
        warns.append("正文出现顿号，独立视觉元素建议用中文逗号分隔")
    if re.search(r"(?<!-)--(?!ar)|---", body):
        errors.append("英文破折号--/---出现在描述词，请使用中文——")
    for duplicate in ["！！", "？？", "～～", "。。。"]:
        if duplicate in quoted:
            errors.append(f"叠字标点「{duplicate}」出现在台词引号内")
    for label in MECHANISM_LABELS:
        if label in management_body:
            errors.append(f"机制/管理标签「{label}」出现在描述词")
    if not layout and ("【" in body or "】" in body):
        errors.append("管理标签【】出现在描述词")
    for placeholder in re.findall(r"\[[^\]\n]{0,100}\]", text)[:8]:
        errors.append(f"占位符残留「{placeholder}」未替换为实际内容")
    for match in re.finditer(r"@(?:素材|图片)\d+\s*锚定", body):
        errors.append(f"旧版锚定句式「{match.group()}」残留，请使用参考声明")

    references = _reference_declarations(text)
    declarations = [slot for slot, _ in references]
    for slot, count in Counter(declarations).items():
        if count > 1:
            errors.append(f"素材位{slot}重复声明")
    for slot in sorted(set(SLOT_RE.findall(text)) - set(declarations)):
        errors.append(f"素材位{slot}被使用但没有独立参考声明")
    if template in {"T6", "T6B"}:
        shot_cells = re.findall(r"(?m)^\s*Shot\s*#([1-9]\d*)[（(]([^）)\n]*)[）)][：:]\s*([^\n]+)", body)
        if shot_cells:
            indices = [int(num) for num, _, _ in shot_cells]
            if indices != list(range(1, 10)):
                errors.append(f"{template}故事板关键帧须按顺序完整包含Shot #1至Shot #9（当前：{indices}）")
            last_cell_time, last_cell_num = None, None
            for num_str, header, _ in shot_cells:
                time_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s(?![A-Za-z]))", header)
                if time_match:
                    cell_time = Decimal(time_match.group(1))
                    if last_cell_time is not None and cell_time < last_cell_time:
                        errors.append(
                            f"{template}故事板关键帧时间节点倒退：Shot #{num_str}（{cell_time}s）早于Shot #{last_cell_num}（{last_cell_time}s）"
                        )
                    last_cell_time, last_cell_num = cell_time, int(num_str)
            cell_bodies = [desc.strip() for _, _, desc in shot_cells]
            if len(set(cell_bodies)) < len(cell_bodies):
                warns.append(f"{template}故事板存在完全重复的Shot关键帧描述；确认是否为合法静止保持，不为填满九格增加剧情、机位或动作")
        if template == "T6B":
            reference_errors, reference_warnings = _check_t6b_references(text)
            errors.extend(reference_errors)
            warns.extend(reference_warnings)
    for slot, declaration in references:
        if _is_voice_reference(declaration):
            if mode != "dynamic":
                errors.append(f"{slot}声音参考仅用于动态视频提示词，不能绑定静态图片模板")
            if slot.startswith("@图片"):
                errors.append(f"{slot}声音参考须使用动态素材位@素材N")
            if quoted_strings(declaration):
                errors.append(f"{slot}声音参考声明含引号内试听文本；试听转写留在声音资产中，本镜实际台词写入镜头正文")
            continue
        scene, ref_what, excluded = _reference_scope(declaration)
        if scene:
            if mode == "dynamic":
                if excluded != {"画面风格", "光影", "色彩"}:
                    errors.append(f"{slot}动态场景/故事板参考缺少禁止继承画面风格、光影、色彩")
                if any(word in ref_what for word in ("画面风格", "光影", "色彩")):
                    errors.append(f"{slot}动态场景/故事板参考不能正向继承画面风格、光影、色彩")
            inherited = {word for word in ("画面风格", "光影", "色彩") if word in ref_what}
            if mode == "static" and template != "T6B" and (inherited & excluded):
                errors.append(f"{slot}静态场景参考的继承项与禁止项冲突")
    visual_body = re.sub(r'“[^”]*”|"[^"\n]*"', "", body)
    for pattern in PHYSICAL_UNITS:
        for value in re.findall(pattern, visual_body):
            errors.append(f"不可识别物理数值「{value}」出现在视觉描述中")
    for pattern in COMPASS_PATTERNS:
        for value in re.findall(pattern, visual_body):
            errors.append(f"罗盘方位词「{value}」须改为建筑或画面相对方位")
    # 光位角度与机位参数可保留；角色动作的数值角度需要视觉化。
    for value in re.findall(r"(?:转头|转身|扭头|抬头|低头|身体旋转)[^，。\n]{0,8}\d+(?:\.\d+)?\s*度", visual_body):
        warns.append(f"角色动作数值角度「{value}」建议改为视觉动作描述")
    # ④情绪目标和台词不是画面动作，不参加抽象情绪词扫描。
    visual_body = re.sub(r"(?m)^\s*整体情绪为[^\n]*", "", visual_body)
    for word in ABSTRACT_EMOTION:
        if word in visual_body:
            warns.append(f"抽象情绪词「{word}」请人工核对其是否属于可见动作描述")
    # 参考声明中的禁止继承是语义隔离协议，不属于尾约束负向堆叠。
    ordinary_body = re.sub(r"(?m)^\s*@(?:素材|图片)\d+\s+参考[^\n]*", "", body)
    if sum(ordinary_body.count(word) for word in ["不要", "禁止", "避免", "切勿"]) >= 3:
        warns.append("正文负向约束堆叠，请以正向视觉事实表达")
    for nonstd, std in SPEED_NONSTD_HINT.items():
        if re.search(rf"语速[^，。\n]{{0,5}}{re.escape(nonstd)}", body):
            warns.append(f"非标准语速词「{nonstd}」，建议「{std}」")

    if mode == "dynamic":
        stamps, timestamp_errors = parse_timestamps(text, duration)
        errors.extend(timestamp_errors)
        for index, stamp in enumerate(stamps):
            end_offset = stamps[index + 1]["offset"] if index + 1 < len(stamps) else len(text)
            chunk = text[stamp["text_offset"]:end_offset]
            unquoted_chunk = QUOTED_RE.sub("", chunk)
            sub_intervals = re.findall(r"\b(\d+\.\d+)\s*[–\-~至]\s*(\d+\.\d+)\s*(?:秒|s)", unquoted_chunk)
            total_dur = stamps[-1]["end"]
            for sub_start_str, sub_end_str in sub_intervals:
                sub_start, sub_end = Decimal(sub_start_str), Decimal(sub_end_str)
                if sub_end < sub_start:
                    errors.append(f"镜头{stamp['index']}内阶段时间区间倒置：{sub_start_str}–{sub_end_str}s")
                elif sub_start < stamp["start"] or sub_start >= stamp["end"] or sub_end > total_dur:
                    errors.append(
                        f"镜头{stamp['index']}（{stamp['start']}-{stamp['end']}s）内阶段时间区间{sub_start_str}–{sub_end_str}s超出有效时间范围"
                    )
            shot_dur = stamp["end"] - stamp["start"]
            if shot_dur <= Decimal("6.0") and len(sub_intervals) >= 5:
                warns.append(
                    f"镜头{stamp['index']}（{shot_dur}s）内含{len(sub_intervals)}个细分时间段，单镜动作密度过高需复核；可合并阶段或延长/拆分，实际承载量以目标模型和返片为准"
                )
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        emotion = next((i for i, line in enumerate(lines) if line.startswith("整体情绪为")), None)
        if emotion is None:
            errors.append("动态描述词缺少④整体情绪为…独立段落")
        else:
            following = []
            for line in lines[emotion + 1:]:
                if line.startswith(("环境音", "BGM", "镜头", "--ar")):
                    break
                following.append(line)
            style = " ".join(following)
            if not style or not re.search(r"风格|画面|光影|光线|渲染|质感|水墨|动漫|写实", style):
                warns.append("未识别出④之后、环境音/镜头之前的⑤视觉风格段，请人工核对；不以关键字证明风格完整")
        ar = re.search(r"(?m)^\s*--ar\s+[^\n]+", text)
        if ar:
            preceding = text[:ar.start()].rstrip().splitlines()
            if preceding and not preceding[-1].strip().startswith("镜头"):
                length = count_words(preceding[-1])
                if not 30 <= length <= 50:
                    warns.append(f"尾约束{length}字，规范为30–50字；请检查末行是否为独立约束段")
            else:
                warns.append("未检测到独立的30–50字尾约束段")
    elif not layout and not 300 <= count_words(text) <= 500:
        warns.append(f"一般静态资产描述词{count_words(text)}字，建议300–500字；复杂版式模板不适用此建议")
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warns))


def _metadata(line: str) -> dict | None:
    match = re.fullmatch(r"\s*<!--\s*prompt\s+(.+?)\s*-->\s*", line)
    if not match:
        return None
    return {m.group(1): m.group(2) if m.group(2) is not None else m.group(3) for m in re.finditer(r'(\w+)=(?:"([^"\n]*)"|([^\s]+))', match.group(1))}


def _looks_like_prompt(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:生成|角色|场景|@(?:素材|图片)\d|镜头\d|--ar)", text))


def extract_prompt_blocks(text: str) -> tuple[list[dict], list[str]]:
    """抽取 text/prompt/无语言提示词块，保留模板/时长/行号元数据。"""
    lines, headings, pending, blocks, notes = text.splitlines(), {}, None, [], []
    saw_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+)", line)
        if heading:
            level = len(heading.group(1))
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = heading.group(2)
            pending = None
        metadata = _metadata(line)
        if metadata is not None:
            pending = metadata
            i += 1
            continue
        opening = re.match(r"^\s{0,3}(`{3,}|~{3,})\s*([^\s]*)[^\n]*$", line)
        if not opening:
            if line.strip() and not heading:
                pending = None
            i += 1
            continue
        saw_fence = True
        fence, language = opening.group(1), opening.group(2).lower()
        start, i = i + 1, i + 1
        content = []
        closing = re.compile(r"^\s{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$")
        while i < len(lines) and not closing.match(lines[i]):
            content.append(lines[i])
            i += 1
        closed = i < len(lines)
        body = "\n".join(content)
        heading_template, heading_mode = None, "auto"
        for title in reversed(headings.values()):
            heading_template = _template(title)
            if heading_template:
                break
            dynamic, static = "动态" in title, "静态" in title
            if dynamic != static:
                heading_mode = "dynamic" if dynamic else "static"
                break
        template = (pending or {}).get("template") or heading_template
        mode_hint = language if language in {"static", "dynamic"} else heading_mode
        eligible = language in {"text", "txt", "prompt", "static", "dynamic"} or (not language and (pending is not None or template is not None or _looks_like_prompt(body)))
        if eligible:
            block = {"text": body, "line": start + 1, "template": template, "prompt_id": (pending or {}).get("id"), "duration": None, "mode_hint": mode_hint, "metadata_errors": []}
            if template and template not in {"T1", "T2", "T3", "T4", "T5", "T6", "T6B", "T6C", "T7", "T8", "T9"}:
                block["metadata_errors"].append(f"未知模板元数据{template}")
            if pending and "duration" in pending:
                try:
                    value = Decimal(pending["duration"])
                    if not value.is_finite():
                        raise InvalidOperation
                    block["duration"] = float(value)
                except (InvalidOperation, ValueError, OverflowError):
                    block["metadata_errors"].append("提示词元数据duration不是有效有限数值")
            if not closed:
                block["metadata_errors"].append("提示词代码块未闭合")
            blocks.append(block)
        pending = None
        i += 1
    if saw_fence and not blocks:
        notes.append("未发现提示词代码块；JSON、Python等管理代码块已跳过，未进行提示词检查")
    if not saw_fence:
        notes.append("no-fences")
    return blocks, notes


def scan_document(text: str, path: str = "<stdin>", mode: str = "auto", duration: float | None = None) -> list[dict]:
    blocks, notes = extract_prompt_blocks(text)
    if not blocks and "no-fences" in notes:
        if Path(path).suffix.lower() == ".md" and (not _looks_like_prompt(text) or re.search(r"(?m)^#{1,6}\s", text)):
            return [{"path": path, "block": None, "line": None, "mode": mode, "errors": [], "warnings": ["未发现提示词代码块或纯文本提示词，规划文档已跳过"], "skipped": True}]
        blocks = [{"text": text, "line": 1, "template": None, "prompt_id": None, "duration": None, "mode_hint": "auto", "metadata_errors": []}]
    if not blocks:
        return [{"path": path, "block": None, "line": None, "mode": mode, "errors": [], "warnings": notes, "skipped": True}]
    results = []
    for i, block in enumerate(blocks, 1):
        requested = mode if mode != "auto" else "auto" if block["template"] else block["mode_hint"]
        actual_mode = _mode(block["text"], requested, block["template"])
        expected = duration if duration is not None else block["duration"]
        errors, warns = check(block["text"], actual_mode, expected, template=block["template"])
        results.append({"path": path, "block": i, "line": block["line"], "prompt_id": block["prompt_id"], "template": block["template"], "mode": actual_mode, "errors": block["metadata_errors"] + errors, "warnings": warns, "skipped": False})
    return results


def scan_file(path: str, mode: str = "auto", duration: float | None = None) -> tuple:
    """兼容旧接口；多个代码块诊断带块号。CLI使用结构化结果。"""
    results = scan_document(Path(path).read_text(encoding="utf-8-sig"), str(path), mode, duration)
    return path, [f"块{r['block']}：{e}" for r in results for e in r["errors"]], [f"块{r['block']}：{w}" for r in results for w in r["warnings"]]


def _extract_dna_clauses(description: str, *, structural_only: bool = False) -> list[tuple[str, list[str]]]:
    """从角色或道具的全局 description 中提取可核对的核心视觉特征子句及其关键词。"""
    stop_prefixes = (
        "年轻", "中年", "老年", "青年", "少年", "东亚", "女性", "男性", "人物", "角色",
        "身形", "身材", "表面", "散布", "细小", "整体", "一件", "一把", "一枚",
    )
    color_words = re.compile(r"黑|白|灰|蓝|红|绿|黄|紫|棕|褐|金|银|铜|青|粉|橙|暗|亮|深|浅")
    results: list[tuple[str, list[str]]] = []
    for raw_clause in re.split(r"[，,、；;。！!\n]+", description):
        clause = raw_clause.strip()
        if len(clause) < 2:
            continue
        cleaned = clause
        for prefix in stop_prefixes:
            if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 1:
                cleaned = cleaned[len(prefix):]
        # 提取2字及以上的连续中文特征词根
        tokens = [t for t in re.findall(r"[\u4e00-\u9fff]{2,}", cleaned) if t not in stop_prefixes]
        if structural_only:
            tokens = [
                re.sub(color_words, "", t) if len(re.sub(color_words, "", t)) >= 2 else t
                for t in tokens
                if not color_words.fullmatch(t)
            ]
        # 提取尾核心名词（如“长衫”、“布鞋”、“窄脸”、“匙柄”、“齿口”）作为回退匹配锚点
        anchors = list(dict.fromkeys(tokens))
        for token in list(tokens):
            if len(token) >= 3:
                anchors.append(token[-2:])
                anchors.append(token[:2])
        if anchors:
            results.append((clause, list(dict.fromkeys(a for a in anchors if len(a) >= 2))))
    return results


def _lighting_tone(text: str) -> str | None:
    cold = bool(re.search(r"冷白|冷光|冷调|冷色|清冷|冷蓝|环境光[^。\n]*?灰蓝", text))
    warm = bool(re.search(r"暖黄|暖金|暖光|暖调|暖色|夕阳金|橘黄|火光暖", text))
    if cold and not warm:
        return "冷调"
    if warm and not cold:
        return "暖调"
    return None


def _visible_character_clauses(clauses, prompt_text, role_text):
    """仅对明确的局部/画外协议缩小启发式核对范围，不从词表推断全部可见性。"""
    if re.match(r"^[ \t]*角色[^：:\n]+[：:]", role_text) and re.search(r"仅画外发声|仅以声音出现|不出镜", role_text):
        return []
    first_shot = re.search(r"(?m)^[ \t]*镜头1[（(]", prompt_text)
    if first_shot is None:
        return clauses
    body = prompt_text[first_shot.start():]
    body = QUOTED_RE.sub("", body)
    body = re.sub(r"不露[^，。\n]{0,8}(?:脸|面部)|脸部不入画", "", body)
    if re.search(r"面部近景|眼部近景|中近景|中景|全景|远景|全身", body):
        return clauses
    visible = None
    if re.search(r"纯手部|仅拍手|仅见手|手部微距", body):
        visible = r"手|腕|指|袖|肤"
    elif re.search(r"纯足部|仅拍脚|足部微距|纯脚部", body):
        visible = r"足|脚|鞋|裤|腿|踝|肤"
    elif re.search(r"纯背影|全程背影", body):
        visible = r"背|发|衣|衫|袍|服|外套|鞋"
    return [item for item in clauses if re.search(visible, item[0])] if visible else clauses


def check_project(
    data: dict,
    previous: dict | None = None,
    path: str = "<project>",
    *,
    source_text: str | None = None,
    shared_assets: dict | None = None,
    media_root: str | Path | None = None,
) -> list[dict]:
    try:
        from .project_data import normalize_dialogue, validate_project, validate_shape
    except ImportError:
        from project_data import normalize_dialogue, validate_project, validate_shape

    extra_kwargs = {}
    if source_text is not None:
        extra_kwargs["source_text"] = source_text
    if shared_assets is not None:
        extra_kwargs["shared_assets"] = shared_assets
    errors, warns = validate_project(data, previous=previous, **extra_kwargs)
    if media_root is not None and isinstance(data, dict) and not validate_shape(data):
        try:
            from .project_data import validate_voice_media
        except ImportError:
            from project_data import validate_voice_media
        media_errors, media_warnings = validate_voice_media(data, media_root)
        errors.extend(media_errors)
        warns.extend(media_warnings)
    if isinstance(data, dict) and not validate_shape(data):
        # 检查同一场景（scene_ids 相同）相邻分镜的光影冷暖基调是否无故突变
        last_scene_tone: dict[tuple[str, ...], tuple[str, str]] = {}
        prompts_by_id = {
            p.get("id"): p for p in data.get("prompts", []) if isinstance(p, dict) and isinstance(p.get("id"), str)
        }
        for shot in data.get("shots", []):
            if not isinstance(shot, dict):
                continue
            scene_key = tuple(shot.get("scene_ids", ()))
            if not scene_key:
                continue
            lighting_decisions = " ".join(
                d.get("decision", "") for d in shot.get("design", []) if isinstance(d, dict) and d.get("role") == "lighting"
            )
            dyn_prompt = prompts_by_id.get(shot.get("dynamic_prompt_id"), {})
            tone = _lighting_tone(lighting_decisions + " " + str(dyn_prompt.get("text", "")))
            if tone:
                if scene_key in last_scene_tone:
                    prev_shot_id, prev_tone = last_scene_tone[scene_key]
                    if prev_tone != tone:
                        warns.append(
                            f"{shot.get('id')}: 与同场景上一镜头 {prev_shot_id} 的光影冷暖基调发生突变（{prev_tone}→{tone}），请核对同场跨镜光影色温一致性"
                        )
                last_scene_tone[scene_key] = (str(shot.get("id")), tone)
    results = [{"path": path, "block": None, "mode": "project", "errors": list(errors), "warnings": list(warns), "skipped": False}]
    if not isinstance(data, dict) or validate_shape(data):
        return results
    shots = {s.get("id"): s for s in data.get("shots", []) if isinstance(s, dict) and isinstance(s.get("id"), str)} if isinstance(data.get("shots"), list) else {}
    characters = {c.get("id"): c for c in data.get("characters", []) if isinstance(c, dict) and isinstance(c.get("id"), str)} if isinstance(data.get("characters"), list) else {}
    props = {p.get("id"): p for p in data.get("props", []) if isinstance(p, dict) and isinstance(p.get("id"), str)} if isinstance(data.get("props"), list) else {}
    for prompt in data.get("prompts", []) if isinstance(data.get("prompts"), list) else []:
        if not isinstance(prompt, dict) or not isinstance(prompt.get("text"), str):
            continue
        template = prompt.get("template")
        mode = _mode(prompt["text"], "auto", template)
        errors, warns = check(prompt["text"], mode, prompt.get("duration"), template=template)
        # 角色与道具跨镜核心外貌 DNA 对账（针对承载全量造型描述的 T1/T2/T6/T6B/T6C/T7/T9）
        if template in {"T1", "T2", "T6", "T6B", "T6C", "T7", "T9"} and isinstance(prompt.get("asset_ids"), list):
            structural_only = template == "T6B"
            for asset_id in prompt["asset_ids"]:
                if asset_id in characters and template in {"T1", "T6", "T6B", "T6C", "T7", "T9"}:
                    char = characters[asset_id]
                    char_name = str(char.get("name", ""))
                    subj_match = re.search(rf"(?m)^\s*角色{re.escape(char_name)}[：:][^\n]+", prompt["text"]) if template in {"T7", "T9"} and char_name else None
                    target_text = subj_match.group(0) if subj_match else prompt["text"]
                    clauses = _extract_dna_clauses(str(char.get("description", "")), structural_only=structural_only)
                    if template in {"T6C", "T7", "T9"}:
                        clauses = _visible_character_clauses(clauses, prompt["text"], target_text)
                    if len(clauses) >= 2:
                        missing = [
                            clause for clause, anchors in clauses
                            if not any(anchor in target_text for anchor in anchors)
                        ]
                        if len(missing) > len(clauses) // 2:
                            warns.append(
                                f"角色{char_name}（{asset_id}）在提示词中的外观描述与全局设定偏离较大（缺少：{'、'.join(missing[:3])}），请核对人物跨镜外貌一致性"
                            )
                elif asset_id in props and template in {"T2", "T6", "T6B", "T6C", "T7", "T9"}:
                    prop = props[asset_id]
                    prop_name = str(prop.get("name", ""))
                    subj_match = re.search(rf"(?m)^\s*道具{re.escape(prop_name)}[：:][^\n]+", prompt["text"]) if template in {"T7", "T9"} and prop_name else None
                    target_text = subj_match.group(0) if subj_match else prompt["text"]
                    clauses = _extract_dna_clauses(str(prop.get("description", "")), structural_only=structural_only)
                    if len(clauses) >= 2:
                        missing = [
                            clause for clause, anchors in clauses
                            if not any(anchor in target_text for anchor in anchors)
                        ]
                        if len(missing) > len(clauses) // 2:
                            warns.append(
                                f"道具{prop_name}（{asset_id}）在提示词中的特征描述与全局设定偏离较大（缺少：{'、'.join(missing[:3])}），请核对道具跨镜一致性"
                            )
        if template in {"T6", "T6B"} and isinstance(prompt.get("shot_id"), str) and prompt["shot_id"] in shots:
            shot = shots[prompt["shot_id"]]
            try:
                shot_dur = Decimal(str(shot.get("duration")))
            except (InvalidOperation, TypeError, ValueError):
                shot_dur = None
            seg_map = {}
            for seg in shot.get("segments", []) if isinstance(shot.get("segments"), list) else []:
                if isinstance(seg, dict) and isinstance(seg.get("index"), int):
                    try:
                        seg_map[seg["index"]] = (Decimal(str(seg.get("start"))), Decimal(str(seg.get("end"))))
                    except (InvalidOperation, TypeError, ValueError):
                        pass
            for num_str, header, _ in re.findall(r"(?m)^\s*Shot\s*#([1-9]\d*)[（(]([^）)\n]*)[）)][：:]\s*([^\n]+)", prompt["text"]):
                time_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s(?![A-Za-z]))", header)
                seg_match = re.search(r"物理镜头\s*([1-9]\d*)", header)
                cell_time = Decimal(time_match.group(1)) if time_match else None
                if cell_time is not None and shot_dur is not None and cell_time > shot_dur:
                    errors.append(f"{template}故事板Shot #{num_str}时间节点（{cell_time}s）超出所属分镜duration（{shot_dur}s）")
                if seg_match:
                    seg_idx = int(seg_match.group(1))
                    if seg_map and seg_idx not in seg_map:
                        errors.append(f"{template}故事板Shot #{num_str}引用了不存在的物理镜头{seg_idx}")
                    elif seg_idx in seg_map and cell_time is not None:
                        s_start, s_end = seg_map[seg_idx]
                        if not (s_start <= cell_time <= s_end):
                            warns.append(
                                f"{template}故事板Shot #{num_str}时间节点（{cell_time}s）超出物理镜头{seg_idx}（{s_start}-{s_end}s）区间，请核对切镜与关键帧时间同步"
                            )
        if mode == "dynamic" and isinstance(prompt.get("shot_id"), str) and prompt["shot_id"] in shots:
            shot = shots[prompt["shot_id"]]
            stamps, _ = parse_timestamps(prompt["text"], prompt.get("duration"))
            if stamps and any(match.start() < stamps[0]["offset"]
                              for match in QUOTED_RE.finditer(prompt["text"])):
                errors.append("提示词首个镜头之前存在引号内台词/OS/NAR，须归入shot.segments并在对应镜头执行")
            segments = shot.get("segments", [])
            if isinstance(segments, list):
                if len(stamps) != len(segments):
                    errors.append("提示词物理镜头数量与shot.segments不一致")
                for index, (stamp, segment) in enumerate(zip(stamps, segments)):
                    if not isinstance(segment, dict):
                        continue
                    try:
                        expected = (segment.get("index"), Decimal(str(segment.get("start"))), Decimal(str(segment.get("end"))))
                        if (stamp["index"], stamp["start"], stamp["end"]) != expected:
                            errors.append(f"镜头{stamp['index']}时间戳与shot.segments不一致")
                    except (InvalidOperation, TypeError, ValueError):
                        continue  # 数据形状错误由validate_project报告。
                    end_offset = stamps[index + 1]["offset"] if index + 1 < len(stamps) else len(prompt["text"])
                    chunk = prompt["text"][stamp["text_offset"]:end_offset]
                    expected_lines = [normalize_dialogue(line["text"]) for line in segment.get("lines", []) if isinstance(line, dict) and isinstance(line.get("text"), str)] if isinstance(segment.get("lines"), list) else []
                    actual_lines = [normalize_dialogue(line) for line in quoted_strings(chunk)]
                    if actual_lines != expected_lines:
                        errors.append(f"镜头{stamp['index']}提示词引号内台词与shot.segments台词文字或顺序不一致")
        results.append({"path": path, "block": None, "prompt_id": prompt.get("id"), "template": template, "mode": mode, "errors": list(dict.fromkeys(errors)), "warnings": warns, "skipped": False})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="逐提示词代码块和结构化项目QC")
    parser.add_argument("target", nargs="?", help="文件或目录；缺省从stdin读取")
    parser.add_argument("--mode", choices=["auto", "static", "dynamic"], default="auto")
    parser.add_argument("--duration", type=float, default=None, help="显式覆盖动态提示词的规定时长")
    parser.add_argument("--project", action="store_true", help="将输入作为project.json检查")
    parser.add_argument("--previous", help="历史project.json，用于修改与版本追溯检查")
    parser.add_argument("--source", help="源剧本或前期交接Markdown，用于校验源稿与JSON台词及映射一致")
    parser.add_argument("--shared-assets", dest="shared_assets", help="跨集共享资产JSON，用于校验公共角色/场景/道具与全局提示词同步")
    parser.add_argument("--media-root", help="声音素材根目录；启用本地母版与投喂副本的存在、指纹及可读取时长检查")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)
    if args.duration is not None and (not Decimal(str(args.duration)).is_finite() or not 5 <= args.duration <= 30):
        parser.error("--duration须为5–30秒范围内的有限数值")
    is_project = args.project or bool(args.target and Path(args.target).suffix.lower() == ".json")
    if (args.previous or args.source or args.shared_assets or args.media_root) and not is_project:
        parser.error("--previous、--source、--shared-assets 与 --media-root 仅用于JSON项目输入")
    results = []
    try:
        if is_project:
            try:
                from .project_data import load_project, parse_project
            except ImportError:
                from project_data import load_project, parse_project
            data = load_project(args.target) if args.target else parse_project(sys.stdin.read())
            previous = load_project(args.previous) if args.previous else None
            source_text = Path(args.source).read_text(encoding="utf-8-sig") if args.source else None
            shared_assets = load_project(args.shared_assets) if args.shared_assets else None
            results = check_project(
                data,
                previous,
                args.target or "<stdin>",
                source_text=source_text,
                shared_assets=shared_assets,
                media_root=args.media_root,
            )
        elif args.target and Path(args.target).is_dir():
            paths = sorted(p for p in Path(args.target).rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"} and p.name != "SKILL.md")
            for path in paths:
                results.extend(scan_document(path.read_text(encoding="utf-8-sig"), str(path), args.mode, args.duration))
            if not paths:
                results = [{"path": args.target, "block": None, "mode": args.mode, "errors": [], "warnings": ["目录中没有可扫描的.md/.txt文件"], "skipped": True}]
        else:
            text = Path(args.target).read_text(encoding="utf-8-sig") if args.target else sys.stdin.read()
            results = scan_document(text, args.target or "<stdin>", args.mode, args.duration)
    except (OSError, UnicodeError, ValueError, TypeError, ImportError) as exc:
        results = [{"path": args.target or "<stdin>", "block": None, "mode": "project" if args.project else args.mode, "errors": [f"无法检查输入：{exc}"], "warnings": [], "skipped": False}]
    if not any(not result.get("skipped", False) for result in results):
        results[0]["errors"].append("未检查到任何提示词或项目数据，不能据此判定QC通过")
    failed = any(result["errors"] for result in results)
    if args.format == "json":
        print(json.dumps({"ok": not failed, "checked": sum(not r.get("skipped", False) for r in results), "skipped": sum(r.get("skipped", False) for r in results), "results": results}, ensure_ascii=False, indent=2))
    else:
        for result in results:
            identity = result.get("prompt_id") or (f"块{result['block']}" if result.get("block") else "")
            print(f"QC {result['path']} {identity} [{result['mode']}]")
            for warning in result["warnings"]:
                print(f"  [WARN] {warning}")
            for error in result["errors"]:
                print(f"  [ERROR] {error}")
            print("  已跳过" if result.get("skipped") else "  不通过" if result["errors"] else "  无ERROR；WARN需人工复核" if result["warnings"] else "  通过")
    return 1 if failed else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
