---
name: ai-short-drama-production
description: 编排中文短剧的选题、故事优化、剧本创作与证据审阅，承接资产节拍、八岗位分镜和静动态提示词，并用本地脚本校验完整项目JSON、导出Markdown制作文档。适用于故事开发到制作方案交付，不调用媒体生成服务或剪辑成片。
metadata:
  version: "V18.3"
  agent_created: true
---

# AI短剧制作编排器

按用户已有材料进入对应阶段，交付故事、剧本、分镜数据与静动态提示词。

## 任务路由

| 任务 | 模块入口 | 交付内容 |
|---|---|---|
| 选题、故事优化、导演风格、剧本审阅 | [sd-story-development/SKILL.md](sd-story-development/SKILL.md) | 选题卡、优化大纲、风格卡、证据审阅报告 |
| 梗概、人物、大纲、场景剧本 | [sd-scriptwriter/SKILL.md](sd-scriptwriter/SKILL.md) | 文学剧本与设定 |
| 资产节拍整理、镜头与声音设计 | [sd-storyboard/SKILL.md](sd-storyboard/SKILL.md) | 八岗位分镜设计与结构化制作数据 |
| 角色、道具、场景、故事板及单帧关键帧提示词 | [sd-static-assets/SKILL.md](sd-static-assets/SKILL.md) | T1–T6/T6B/T6C静态提示词 |
| 视频提示词、配音与音效脚本 | [sd-dynamic-video/SKILL.md](sd-dynamic-video/SKILL.md) | T7–T9动态提示词与声音脚本 |
| 角色声音设计与视频音色参考 | [references/voice-reference-assets.md](references/voice-reference-assets.md) | 声音卡、试听文案、母版与模型副本、音频槽绑定 |

## 执行约定

1. 沿用已有材料与范围，只补问影响当前交付的缺失信息；局部任务直接交付对应结果。
2. 完整制作先固定源剧本基线，再映射资产、节拍与原台词；回改按“源剧本 → 交接记录 → 受影响实体增版 → 捕获依赖 → QC → 导出”同步。
3. 实际提示词使用独立`text`代码块，设计说明、素材映射和检查结果放在代码块外。

## 公共参考

- [制作流程](references/production-workflow.md)：阶段交接、源稿映射与回改同步。
- [整场预算](references/scene-timing.md)：动作、对白、反应与证据阅读的时间预算。
- [项目数据](references/project-data.md)：`project.json`字段关系、素材绑定与依赖快照。
- [公共规则](references/rule-authority.md)：跨模块规则编号（`R-*`）、画幅与参考继承。
- [声音参考资产](references/voice-reference-assets.md)：视频模型角色声音参考与返片听审。
- [尾约束写法](references/constraints.md)：提示词末尾30–50字正向质量约束。
- [本地工具](references/tools.md)：`qc_check.py`、`project_data.py`、`render_project.py`、`slice_grid.py`用法。
