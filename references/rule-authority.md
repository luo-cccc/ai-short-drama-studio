# 跨模块公共规则

本表维护跨模块的制作约定与`R-*`规则标识。提示词字段以各模块`templates.md`为准，数据字段以`schemas/project.schema.json`为准，校验与导出逻辑见`scripts/`。

## 优先级

1. 用户当前指令与明确范围优先。
2. 本表定义跨模块规则；静态与动态模块的`templates.md`定义提示词结构。
3. `schemas/project.schema.json`定义JSON字段结构，`scripts/`实现程序化校验与导出。

## 规则清单

| ID | 适用范围 | 规则内容 | 详细参考 |
|---|---|---|---|
| R-WORKFLOW-001 | 完整制作 | 按“选题与故事优化 → 剧本与审阅 → 资产节拍与预算 → 八岗位分镜 → 静动态提示词 → JSON校验与导出”推进；局部任务直接交付请求范围。 | [production-workflow.md](production-workflow.md) |
| R-BASELINE-001 | 剧本交接 | 登记源剧本版本、采用范围、审阅状态；动作与台词保留源定位并映射稳定ID。回改先更新源稿与交接记录，再同步下游实体与快照。 | [production-workflow.md](production-workflow.md) |
| R-DEVELOP-001 | 前期开发 | Type A/B/C/D表示叙事推进路线，与写实/2D/3D视觉形态及导演风格分别记录；审阅问题须绑定原稿证据位置。 | [sd-story-development](../sd-story-development/SKILL.md) |
| R-TEXT-001 | 字幕与UI | 区分角色台词、画内文字与后期叠字。动态提示词默认无字幕；画内文字与后期叠字记录于`shots.overlays`或交接表。 | [production-workflow.md](production-workflow.md) |
| R-STRUCT-001 | T1–T6/6B/6C | 六层语义顺序：任务、主体、场景、情绪目标（条件层）、视觉风格、质量约束；参考声明置顶，`--ar`画幅参数独占末行。 | [静态模板](../sd-static-assets/references/templates.md) |
| R-STRUCT-002 | T7–T9 | 六层顺序：任务、主体固有外观、场景空间、整体情绪目标、视觉风格、镜头脚本；环境音与BGM在镜头块前，尾约束在末镜后、`--ar`前。 | [动态模板](../sd-dynamic-video/references/templates.md) |
| R-VISUAL-001 | 提示词正文 | 画面段写可见外观、动作与空间；声音段写声源与台词表演；设计依据、模板标签与占位符不进入提示词代码块。 | [static-rules.md](../sd-static-assets/references/static-rules.md)、[dynamic-rules.md](../sd-dynamic-video/references/dynamic-rules.md) |
| R-PARAM-001 | 参数规范 | 机位与光影可用焦距、光圈、色温、光位角度并配视觉效果描述；主体动作不写量化角度，正文禁用物理尺寸、速度（m/s）、重量（kg）、照度（lux）、分贝（dB）、ISO、快门及罗盘方位词（东南西北）。 | [qc_check.py](../scripts/qc_check.py) |
| R-SPACE-001 | 分镜时长与拆分 | 单个`SHOT`为5–30秒；超出承载量时延长或拆分为多个分镜，不为凑镜数删减剧情或按台词条数机械切镜。 | [storyboard-rules.md](../sd-storyboard/references/storyboard-rules.md) |
| R-TIME-001 | 动态镜头时间戳 | 格式为`镜头1（0.0-5.0s）：`，序号从1连续递增，首段从`0.0`起，相邻段首尾相接，一位小数，总长等于分镜`duration`。 | [动态模板](../sd-dynamic-video/references/templates.md) |
| R-TIME-002 | 整场时间预算 | 先排对白、操作、反应、证据阅读和转场的顺序与并行区间，再划分制作片段；局部时间小于等于6.0秒且含5个及以上细分时段时触发高密度WARN。 | [scene-timing.md](scene-timing.md) |
| R-SHOT-001 | 镜头过程与切点 | 明确主体、相对机位、起幅、运动过程与落幅；证据阅读窗口从对象清楚可辨时起算；切点落在具体动作、目光、物件或声音节点，八岗位、`segments.description`、故事板与动态正文保持一致。 | [storyboard-rules.md](../sd-storyboard/references/storyboard-rules.md) |
| R-REF-001 | 视觉参考声明 | 静态用`@图片N`，动态用`@素材N`；正向参考与`禁止继承`不得矛盾，声明主语与绑定实体类别/名称一致。跨状态T1/T2/T3绑定母图锁死骨相/器型/建筑拓扑并禁旧状态；T6B仅继承结构；引用T6/T6B切片时禁止继承人物五官面容；动态场景/故事板参考必须`禁止继承画面风格、光影、色彩`。 | [project-data.md](project-data.md)、[qc_check.py](../scripts/qc_check.py) |
| R-VOICE-001 | 声音参考资产 | 声音卡与母版保存稳定音色、口音和咬字，按`audio_reference_profile`绑定模型副本。声明只参考声音身份，禁止继承样片台词、情绪、语速、背景声音；样片转写与`audition_text`不进入`dialogues`或镜头台词引号。 | [voice-reference-assets.md](voice-reference-assets.md) |
| R-CONSIST-001 | 跨镜一致性 | 角色`description`包含至少2项不可变面部骨相特征与默认服装；露脸镜头保留骨相DNA，局部手足/纯背影移除不可见五官词；多人同框逐角色内联绑定槽位与画面方位；同场景跨镜保持光影色温连续（有剧情动机变化除外）；未绑音频槽时发声镜头沿用`characters.voice`核心声线词。 | [static-rules.md](../sd-static-assets/references/static-rules.md)、[dynamic-rules.md](../sd-dynamic-video/references/dynamic-rules.md) |
| R-LIGHT-001 | 空间光与叙事光 | T3/T4/T5使用基础漫射可读光；镜头叙事光影在故事板（T6/T6C）与动态风格层定义。T6B线稿仅作结构参考，写实/彩色首尾帧须使用T6C重绘全分辨率目标风格单帧。 | [design-9b.md](../sd-storyboard/references/design-9b.md) |
| R-ASPECT-001 | 模板画幅 | T1/T3/T4固定`16:9`，T2固定`3:4`，T5/T6/T6B/T6C/T7/T8/T9跟随`project.aspect_ratio`；T5/T6/T6B内部3×3单格与外画幅同构，满幅无字。 | [静态模板](../sd-static-assets/references/templates.md) |
| R-CONSTRAINT-001 | 提示词尾约束 | 正文末尾、`--ar`前写一段30–50字正向描述，交代当前画面特有的数量、接触关系与可见范围，禁用管理标签与否定词堆叠。 | [constraints.md](constraints.md) |
| R-LENGTH-001 | 静态字数建议 | T1–T4建议300–500字，T5/T6/T6B以九格字段完整为准，动态提示词不限固定字数。 | [qc_check.py](../scripts/qc_check.py) |
| R-TABLE-001 | 总分镜表 | `project.md`导出固定15列总分镜表。 | [render_project.py](../scripts/render_project.py) |
| R-DATA-001 | 依赖快照 | `shots`与`prompts`在`depends_on`保存直接依赖的`id`、`revision`与SHA-256指纹；修改上游后须重做下游内容并运行`capture`。 | [project-data.md](project-data.md) |
| R-QC-001 | 校验范围 | JSON QC检查Schema、引用关系、台词顺序、时间轴、依赖快照与每条提示词；Markdown/文本QC仅检查独立提示词块。 | [tools.md](tools.md) |
