---
name: sd-storyboard
description: 将采用的场景剧本转为分镜、八岗位设计与资产规划，整理结构化制作数据并导出逐镜文档。适用于完整制作或指定范围的分镜规划，剧情回改交回编剧，媒体由外部工具生成。
metadata:
  version: "V18.3"
  agent_created: true
---

# 分镜设计与制作规划

将源剧本转化为资产清单、剧情节拍、八岗位分镜与静动态提示词规划，并维护`project.json`。

## 制作步骤

1. **整理资产与节拍**：按[制作流程](../references/production-workflow.md)提取`CHAR-`、`SCENE-`、`PROP-`、`BEAT-`、`LINE-`及源定位映射；涉及声音参考时按[声音参考资产](../references/voice-reference-assets.md)登记`VOICE-`资产。
2. **整场预算与分段**：按[整场时间预算](../references/scene-timing.md)排定动作、对白、反应与证据可读时间，划分5–30秒的`SHOT`及内部物理镜头（`segments`）。
3. **八岗位协同设计**：按[9B八岗位设计](references/design-9b.md)完成`director`、`camera`、`lighting`、`action`、`staging`、`dialogue`、`sound`、`vfx`决策。
4. **镜头与衔接复核**：按[分镜设计方法](references/storyboard-rules.md)与[分镜审阅清单](references/quality-gates.md)检查轴线、关键帧、转场和跨镜一致性。
5. **写入数据与导出**：调用[静态资产](../sd-static-assets/SKILL.md)和[动态视频](../sd-dynamic-video/SKILL.md)模板组装`project.json`，使用[本地工具](../references/tools.md)捕获依赖快照、运行QC并导出文档。

## 模板分工

| 资产或镜头类型 | 对应模板 |
|---|---|
| 角色、道具、场景概念及扩图 | 静态`T1`、`T2`、`T3`、`T4` |
| 场景九视角空间参考 | 静态`T5`（同画幅满幅3×3无字九视角，用`slice_grid.py --grid-kind spatial`切分） |
| 3×3关键帧故事板与单帧首尾帧重绘 | 静态`T6`（彩色）、`T6B`（黑白线稿）、`T6C`（全分辨率单帧关键帧重绘） |
| 动态视频提示词 | 动态`T7`（文生）、`T8`（图生）、`T9`（图文混合，完整分镜默认） |

## 导出文档结构

- `project.md`：项目全局设定、角色声音参考资产库（如有）、剧本节拍与原始台词、全局静态资产总库、15列总分镜表。
- `SHOT-ID_分镜.md`：第一章分镜设计思维、第二章静态资产描述词、第三章动态视频描述词、第四章配音与音效脚本、第五章素材位对照与资产清单。

### 总分镜表15列字段

镜号、合规时长档位、分镜核心功能、核心剧情梗概、分镜头数量、切镜节奏、核心镜头语言设计、核心光影基调、关键音频节点、转场设计、核心配音台词内容、参考素材资产、9B设计编号、9B-1B审查状态、备注。
