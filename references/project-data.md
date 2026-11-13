# 项目数据契约

`project.json`保存完整制作数据，字段定义以[schemas/project.schema.json](../schemas/project.schema.json)为准，校验逻辑见`scripts/project_data.py`与`scripts/qc_check.py`。

## 顶层结构与实体ID

文件采用UTF-8编码（允许BOM），禁止注释、重复键、非有限数值或未知字段。`schema_version`支持`"1.0"`和`"1.1"`（含`voices`、`audio_reference_profile`或`VOICE-`绑定时须为`"1.1"`）。

| 顶层字段 | ID前缀 | 数量要求 | 说明 |
|---|---|---|---|
| `project` | `PRJ-` | 必填对象 | `id`、`revision`、`title`、`aspect_ratio`（`9:16` / `16:9` / `2.39:1`）、`style` |
| `characters` | `CHAR-` | `>= 0` | `name`、`description`（含不可变面部骨相DNA与默认服装）、`voice`（声线摘要） |
| `scenes` | `SCENE-` | `>= 1` | `name`、`description`（前景/中景/背景/远景与定锚物） |
| `props` | `PROP-` | `>= 0` | `name`、`description`（器型构造、材质与特征） |
| `beats` | `BEAT-` | `>= 1` | `scene_id`、`summary`、`character_ids`、`prop_ids`，可选`source_ref` |
| `dialogues` | `LINE-` | `>= 0` | `beat_id`、`speaker_id`、`kind`（`dialogue` / `os` / `narration`）、`text`，可选`source_ref` |
| `shots` | `SHOT-` | `>= 1` | 5–30秒制作片段，含`segments`、`design`、`audio`、`transitions`、`review`、`notes`及可选`overlays` |
| `prompts` | `PROMPT-` | `>= 1` | `template`（`T1`–`T6C` / `T7`–`T9`）、`shot_id`、`duration`、`asset_ids`、`reference_bindings`、`text` |
| `voices` | `VOICE-` | `1.1`可选 | 角色或旁白的声音身份参考，含`status`、`audition`、`master`、`references`及可选`audition_text` |

所有实体均含全局唯一`id`（前缀+字母数字/下划线/连字符）与正整数`revision`。修改实体内容时递增`revision`，重命名或重排不更换`id`。

## 核心校验规则

### 1. 节拍、分镜与八岗位
- 每个`BEAT-`至少被一个`SHOT-`认领；认领分镜的`scene_ids`、`character_ids`、`prop_ids`须包含该节拍登记的场景、角色与道具。
- 每个`SHOT-`至少引用一条静态提示词（`static_prompt_ids`），且唯一对应一条动态提示词（`dynamic_prompt_id`）。
- 静态提示词（`T1`–`T6`、`T6B`、`T6C`）的`duration`必须为`null`，`shot_id`为`null`时表示全局静态资产；动态提示词（`T7`–`T9`）必须归属唯一`shot_id`，`duration`与所属分镜一致，`asset_ids`包含该分镜的全部角色、场景与道具。
- `shot.design`必须包含8个不同`role`（`director`、`camera`、`lighting`、`action`、`staging`、`dialogue`、`sound`、`vfx`），每项含非空`knowledge`与`decision`。
- `shot.review`包含`9B-`前缀的`design_id`及`status`（`unreviewed` / `needs_revision` / `approved`）。
- `shot.overlays`（可选）记录画内文字或后期字幕：`kind`（`in_scene` / `post_subtitle` / `post_ui` / `post_graphic`）、`text`、`method`，以及可选的成对`start/end`与`position`。

### 2. 台词与时间轴
- `dialogues.kind`为`dialogue`或`os`时必须指定`speaker_id`（且该角色须在对应`beat.character_ids`和执行分镜`shot.character_ids`中）；仅`narration`允许`speaker_id: null`。
- 按`shots -> segments -> lines`顺序遍历，所有`dialogues`须恰好执行一次且顺序一致。文本对账经Unicode NFC归一化并忽略标点与空白。
- `shot.duration`为5–30秒（0.1秒步长）。`segments`序号从1连续递增，首段从`0.0`开始，相邻段首尾相接，末段终点等于`shot.duration`。动态提示词正文中的`镜头N（start-ends）：`须与`segments`的数量、时间戳及引号内台词一致。
- `segments.lines`含`dialogue_id`与`text`，可成对填写局部时间`start`与`end`（`segment.start <= start < segment.end`，`start < end <= shot.duration`，同镜内按顺序不回退）。跨切镜台词归属开始发声的`segment`。

### 3. 素材绑定与画幅
- `reference_bindings`含`slot`与`asset_id`（声音绑定另含`audio_reference_id`）。静态提示词使用`@图片N`，动态提示词使用`@素材N`，正文使用的槽位集合须与`reference_bindings`完全一致，且每个槽位在正文有独立参考声明。
- 绑定`CHAR-`、`SCENE-`、`PROP-`、`VOICE-`时，该ID须同时列入`prompt.asset_ids`；也可绑定静态`PROMPT-`（禁止绑定动态`PROMPT-`或跨分镜绑定其他镜头的`T6`/`T6B`故事板）。
- 参考声明与主体行中的资产类别、名称必须与绑定的实体一致。动态提示词的场景/故事板参考必须包含`禁止继承画面风格、光影、色彩`且不得正向继承这些属性；正向参考项与禁止继承项不得冲突。
- 每条提示词末行须唯一声明`--ar 比例`：`T1`/`T3`/`T4`固定为`16:9`，`T2`固定为`3:4`，`T5`/`T6`/`T6B`/`T6C`/`T7`/`T8`/`T9`跟随`project.aspect_ratio`。
- `T6`/`T6B`包含`Shot #`行时，须按序包含`Shot #1`至`Shot #9`，标定时间不回退、不超出分镜`duration`，引用的`物理镜头N`须存在于`shot.segments`。

### 4. 角色声音参考（Schema 1.1）
- `voices[].status`为`planned`时，`master`须为`null`、`references`须为空数组、`audition`不得为`approved`，且不得绑定到动态提示词槽位。
- `status`为`ready`时须提供`master`（含本地相对路径`path`、64位小写十六进制`sha256`、`duration`、`transcript`）。
- `references`记录按模型裁剪的投喂副本（`id`、`model_id`、`path`、`sha256`、`duration`、`source_start`、`source_end`、`transcript`），裁剪区间须在母版时长内且`|source_end - source_start - duration| <= 0.05`。
- 动态提示词绑定`VOICE-`时须提供`audio_reference_profile`（`model_id`、`supports_voice_reference: true`、`max_files`、`max_file_duration`、`max_total_duration`、`formats`、`source`），副本`model_id`、文件数、时长与扩展名须符合配置。同一角色或旁白在同一提示词中只能绑定一个声音参考。

## 依赖快照（`depends_on`）

`shots`和`prompts`通过`depends_on`记录直接依赖的`id`、`revision`与SHA-256 `fingerprint`（对排除`depends_on`后的实体JSON计算）：

| 衍生实体 | 必须记录的直接依赖 |
|---|---|
| `SHOT-` | `project.id`、`scene_ids`、`character_ids`、`prop_ids`、`beat_ids`、`segments[].lines[].dialogue_id` |
| `PROMPT-` | `project.id`、`asset_ids`、`reference_bindings[].asset_id`、非空`shot_id` |

上游实体内容或`revision`变化会使下游快照失效；使用`project_data.py capture`在完成下游内容修订后更新快照。
