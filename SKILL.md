---
name: ai-short-drama-production
description: 编排中文短剧的剧本、分镜、生图与视频提示词创作，并用本地脚本校验完整项目JSON、导出Markdown制作文档。适用于制作方案与提示词交付，不负责调用媒体生成服务或剪辑成片。
metadata:
  version: "V18.0"
  agent_created: true
---

# AI短剧制作编排器

根据用户已有材料选择制作环节，维护剧本、资产与分镜之间的关系。仓库提供创作方法、提示词模板和本地数据工具；实际文件与命令见 [README.md](README.md)。

## 路由

| 任务 | 技能入口 | 交付 |
|---|---|---|
| 大纲、人物、场景剧本 | [sd-scriptwriter](sd-scriptwriter/SKILL.md) | 文学剧本 |
| 剧情拆分、镜头设计、声音与衔接 | [sd-storyboard](sd-storyboard/SKILL.md) | 分镜设计与制作数据 |
| 角色、道具、场景、故事板 | [sd-static-assets](sd-static-assets/SKILL.md) | T1–T6/6B 静态提示词 |
| 运镜、动作、配音与音效 | [sd-dynamic-video](sd-dynamic-video/SKILL.md) | T7–T9 动态提示词和音频脚本文本 |

完整制作按剧本→分镜设计→静态与动态提示词推进。局部任务直接进入相应模块；已有剧本或资产可复用，不要求重做已完成环节。

## 工作方式

1. 从用户材料确定品类、画幅、故事范围及所需交付，只补问影响当前任务的信息。
2. 创作与审查分阶段进行。按用户约定提交全局设定、资产方案和逐镜设计；已有授权覆盖的批次可继续。八岗位设计方法见分镜技能。
3. 需要结构化交付时，按数据契约维护 project.json。当前Schema校验完整制作项目，阶段草稿和独立文学剧本可先以Markdown审阅。
4. 完整数据通过项目QC后导出 project.md 与逐镜文档。修改上游时检查依赖快照，重做受影响内容后显式捕获新快照，再重新校验。

设计审查与用户确认由Agent和制作人员执行。review.status是项目记录，Python工具不执行审批门控；示例保留未审查状态。程序化检查不能判断实际画面、动作物理或艺术效果。

## 按需读取

| 内容 | 文件 | 何时读取 |
|---|---|---|
| 规则范围与冲突优先级 | [rule-authority.md](references/rule-authority.md) | 首次跨模块制作或处理规范冲突 |
| 制作审查索引 | [core-rules.md](references/core-rules.md) | 核对角色、空间、叙事和设计连续性 |
| 尾部质量约束写法 | [constraints.md](references/constraints.md) | 编写提示词收尾段 |
| 数据、命令与工具边界 | [project-data.md](references/project-data.md) | 建立完整JSON、修改追溯、QC和导出 |

静态与动态模板正文分别由对应模块的 templates.md 维护；数据字段以 schemas/project.schema.json 为准，不在入口复制完整定义。模板中的方括号是写作占位，交付时替换为实际内容；每条实际提示词单独放在可复制代码块中。
