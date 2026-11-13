# 故事开发到制作交付

完整制作按下表推进；已有材料从对应阶段进入，局部任务仅交付请求范围。数据字段见[项目数据](project-data.md)，命令见[本地工具](tools.md)，跨模块规则见[公共规则](rule-authority.md)。

## 阶段与交付

| 阶段 | 入口 | 交付内容 |
|---|---|---|
| 1. 选题与故事优化 | [sd-story-development](../sd-story-development/SKILL.md) | 选题卡、优化大纲（人物目标、阻力、代价、回报与范围），按需附风格卡 |
| 2. 剧本编写与审阅 | [sd-scriptwriter](../sd-scriptwriter/SKILL.md)、[剧本审阅](../sd-story-development/references/script-review.md) | 源剧本、证据审阅结论与制作采用的基线版本 |
| 3. 资产与节拍整理 | [sd-storyboard](../sd-storyboard/SKILL.md)、[整场预算](scene-timing.md) | 稳定资产ID、动作与信息节拍、原台词及源定位、整场时间预算与分段边界 |
| 4. 八岗位分镜 | [9B八岗位设计](../sd-storyboard/references/design-9b.md) | 逐镜八岗位决策、物理镜头（`segments`）、时长、声音与转场 |
| 5. 提示词与素材绑定 | [sd-static-assets](../sd-static-assets/SKILL.md)、[sd-dynamic-video](../sd-dynamic-video/SKILL.md) | T1–T9提示词、参考素材位绑定与完整`project.json` |
| 6. 校验与导出 | [本地工具](tools.md) | 通过QC的`project.json`，导出`project.md`、`SHOT-ID_分镜.md`与`.drama-export.json` |

## 项目文件约定

| 文件 | 用途 |
|---|---|
| `preproduction.md` 或 `片名_场景剧本.md` | 源剧本、开发摘要、整场时间预算与源定位映射（示例见`examples/demo/preproduction.md`） |
| `project.json` | 完整结构化制作数据与`depends_on`依赖快照（示例见`examples/demo/project.json`） |
| `output/<project>/` | `render_project.py`生成的`project.md`、`SHOT-ID_分镜.md`与`.drama-export.json` |

多集项目可分集建目录，通过`project_data.py sync-assets`同步公共角色、场景、道具、声音及全局静态提示词。

## 制作交接要点

1. **基线与范围**：记录源剧本版本、采用场次、审阅状态、项目画幅（`9:16` / `16:9` / `2.39:1`）、视觉形态与导演叙事风格。
2. **整场时间预算**：按[整场预算](scene-timing.md)排定对白、操作、反应、证据阅读和转场的顺序与并行区间，建立场内总轴与各`SHOT`局部轴（0.0秒起）的映射。
3. **源稿到制作数据映射**：
   - 登记角色（`CHAR-`）、场景（`SCENE-`）、道具（`PROP-`）。
   - 提取行动与信息变化节拍（`BEAT-`），覆盖采用范围内的全部动作。
   - 按执行顺序登记台词（`LINE-`），保留说话者、类型（`dialogue` / `os` / `narration`）与原文；可用`source_ref`记录源定位锚点。
   - 按5–30秒承载量划分制作片段（`SHOT-`）及内部物理镜头（`segments`），完成八岗位设计后编写提示词（`PROMPT-`）。
4. **文字与声音**：
   - 动态提示词默认无字幕。画内文字与后期叠字写入`shots.overlays`（导出至分镜文档第五章）或在交接文档单列。
   - 使用视频模型声音参考时，按[声音参考资产](voice-reference-assets.md)登记`VOICE-`资产、母版与模型副本；样片转写与`audition_text`不进入`dialogues`或镜头台词引号。

## 回改同步顺序

源稿或上游设定变更时，按以下顺序更新：

1. 修订源剧本与`preproduction.md`交接映射。
2. 修改受影响的资产、节拍、台词、分镜设计与提示词，并递增对应实体的`revision`。
3. 运行`project_data.py capture`更新`depends_on`依赖快照。
4. 运行`qc_check.py project.json --source preproduction.md --previous old_project.json`核对一致性。
5. 运行`render_project.py`重新导出Markdown文档。
