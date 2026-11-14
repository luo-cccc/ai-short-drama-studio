---
name: sd-dynamic-video
description: 将短剧分镜设计转为视频提示词及声音文本，按角色绑定视频模型的声音参考。用于文生、图生、混合参考模式的镜头、动作、声音与时长编排；本模块不调用视频或语音生成服务。
metadata:
  version: "V18.3"
  agent_created: true
---

# 动态视频提示词与声音脚本

将八岗位分镜设计转为动态视频提示词（`T7`–`T9`）、角色声线、对白及音效/BGM脚本，并按需绑定角色声音参考。

## 模板选择

| 模板 | 适用场景 | 视觉描述职责 |
|---|---|---|
| `T7` | 文生视频（无参考图） | 全量文字描述角色、场景、道具、光影与镜头动作 |
| `T8` | 图生视频（以图为主） | 声明`@素材N`继承范围，文字补充动态、情绪、叙事光影与声音 |
| `T9` | 图文混合参考（完整分镜默认） | `@素材N`参考声明 + 全量角色/场景/道具/光影/镜头文字描述 |

每个发声角色最多保留单条声音参考（`VOICE-`），独立于`T7`/`T8`/`T9`的视觉模式，按[声音参考资产](../references/voice-reference-assets.md)在发声分镜绑定音频槽与`audio_reference_profile`，不额外预生成整集配音资产。

## 编写与交付

1. 按[整场时间预算](../references/scene-timing.md)确定分镜`duration`（5–30秒）、内部物理镜头（`segments`）与台词发声区间（预留首尾口型缓冲）。
2. 从[动态模板](references/templates.md)选取模板组装独立`text`代码块：
   - 环境音与BGM置于镜头块前；动作音效、角色对白、OS与NAR放入所属`镜头N（start-ends）：`内。
   - 台词引号内文字与顺序须与`segments.lines`及源剧本严格一致；计划发声区间写入`segments.lines[].start/end`。
   - 正文末尾、`--ar`前写一段30–50字[正向尾约束](../references/constraints.md)。
3. 运镜过程、跨镜一致性与特殊场景稳定策略见[动态设计方法](references/dynamic-rules.md)。
