---
name: ai-short-drama-production
description: 编排中文短剧的选题、故事优化、剧本创作与证据审阅，承接资产节拍、八岗位分镜和静动态提示词，并用本地脚本校验完整项目JSON、导出Markdown制作文档。适用于故事开发到制作方案交付，不调用媒体生成服务或剪辑成片。
metadata:
  version: "V18.1"
  agent_created: true
---

# AI短剧制作编排器

按用户已有材料选择阶段，交付故事、剧本、制作数据和提示词。完整流程见[制作流程](references/production-workflow.md)，本地工具用法见[项目数据与工具](references/project-data.md)。

## 任务路由

| 任务 | 入口 | 交付 |
|---|---|---|
| 选题、故事优化、导演风格、剧本审阅 | [前期开发](sd-story-development/SKILL.md) | 选题卡、优化大纲、风格卡、证据审阅 |
| 梗概、人物、大纲、场景剧本 | [编剧](sd-scriptwriter/SKILL.md) | 文学剧本 |
| 资产节拍整理、镜头与声音设计 | [分镜](sd-storyboard/SKILL.md) | 八岗位设计和制作数据 |
| 角色、道具、场景、故事板提示词 | [静态资产](sd-static-assets/SKILL.md) | T1–T6/6B |
| 视频提示词、配音与音效脚本 | [动态视频](sd-dynamic-video/SKILL.md) | T7–T9及声音文本 |

## 执行约定

1. 沿用已有材料、范围和授权，只补问影响当前结果的信息。局部任务直接交付所需内容；已有剧本不重复选题。
2. 完整制作先固定采用的剧本版本，再将动作、资产和原台词映射为制作数据。源稿回改时先修订基线，再更新下游。
3. 按用户约定审阅阶段或批次。专业审阅、用户确认和程序QC分别记录，不互相替代。
4. 实际提示词各用独立可复制代码块；设计依据、素材映射和检查结果放在块外。完整JSON通过QC后再导出Markdown。

## 按需读取

- [制作流程](references/production-workflow.md)：阶段交付、基线、制作交接和回改。
- [公共规则](references/rule-authority.md)：跨模块层序、画幅、时长和参考继承。
- [项目数据与工具](references/project-data.md)：字段关系、依赖快照、QC和导出。
- [尾约束写法](references/constraints.md)：编写具体画面的质量约束。

提示词字段以各模块templates.md为准，数据字段以schemas/project.schema.json为准。
