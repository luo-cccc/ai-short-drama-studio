# 项目数据契约

`project.json`保存完整制作数据，Markdown是导出视图。字段、类型和必填项以[Schema](../schemas/project.schema.json)为准；命令见[本地工具](tools.md)，源稿交接见[制作流程](production-workflow.md)。

## 实体与版本

文件使用UTF-8，可带BOM；不接受注释、尾逗号、重复键、非有限数值或未知字段。`schema_version`支持`1.0`和`1.1`，声音参考字段使用`1.1`。

| 数据 | ID前缀 | 内容 |
|---|---|---|
| `project` | PRJ- | 标题、主画幅、风格；画幅可选9:16、16:9、2.39:1 |
| `characters` | CHAR- | 名称、视觉设定、简短声线摘要`voice` |
| `scenes` | SCENE- | 可复用物理场景 |
| `props` | PROP- | 可复用道具 |
| `beats` | BEAT- | 源稿顺序、场景、动作/信息变化及涉及资产 |
| `dialogues` | LINE- | 节拍、说话者、类型和原文；数组定义执行顺序 |
| `shots` | SHOT- | 制作片段、物理镜头、八岗位、声音、转场与审阅状态 |
| `prompts` | PROMPT- | 模板、所属分镜、资产、参考绑定、正文及依赖快照 |
| `voices`（1.1可选） | VOICE- | 视频模型的角色声音参考 |

除`voices`外，上述对象和数组均须存在；`scenes`、`beats`、`shots`、`prompts`至少一项，角色、道具和台词可为空。允许空值不等于可省略字段，例如`notes: ""`、`lines: []`、静态提示词`duration: null`。

实体均有稳定`id`和从1开始的整数`revision`。ID后缀由英文字母、数字、下划线和连字符组成，首字符为字母或数字；全项目唯一，排序或改名不重发ID，内容变更增加版本。

## 关系与时间

### 节拍、分镜和提示词

- 每个beat至少由一个shot认领；认领分镜须登记其场景、角色和道具。
- 每个shot至少引用一条静态提示词，并唯一拥有一条动态提示词。动态时长须与shot一致，`asset_ids`包含本镜角色、场景和道具。
- 静态模板为T1–T6、T6B及T6C，`shot_id`可为空供全局复用；动态模板为T7–T9，须归属一个shot。
- `design`由`role`、`knowledge`、`decision`组成，八个role各一次：`director`、`camera`、`lighting`、`action`、`staging`、`dialogue`、`sound`、`vfx`。
- `audio`包含`ambience`、`music`、`effects`；`transitions`包含`incoming`、`outgoing`；`review`包含`9B-`前缀的`design_id`及`unreviewed/needs_revision/approved`状态。该状态展示于导出文档，不阻止QC或导出。
- `shots.overlays`（可选）记录画内文字与后期叠字：`kind`（`in_scene/post_subtitle/post_ui/post_graphic`）、`text`、`method`及可选的成对局部时间`start/end`和`position`，导出于分镜文档第五章。

### 台词与局部时间

`dialogues.kind`为`dialogue`、`os`或`narration`，仅`narration`允许`speaker_id: null`。角色画外对白仍保留角色身份；OS为内心独白，NAR为叙述。指定角色须属于对应节拍及执行台词的分镜。

按shots、segments、lines顺序遍历，全部台词须恰好出现一次，顺序与`dialogues`一致。文字对账先做Unicode NFC归一化，再忽略标点与空白，保留字词、数字和其他符号。源锚点须唯一；`--source`额外核对源稿台词、说话者、类型和定位映射。

每个shot为5–30秒，时间采用0.1秒步长。`segments`是物理镜头：编号从1连续、首镜从0开始、区间首尾相接、每镜时长为正、末镜终点等于shot时长。动态正文使用`镜头1（0.0-5.0s）：`格式，时间恰好一位小数，并与segments对账。

`segments.lines`记录`dialogue_id`与执行`text`，可成对填写`start/end`作为计划发声区间：起点落在所属物理镜头`[start, end)`内，终点晚于起点且不超过shot，同一shot内台词起点按执行顺序不回退。同一句可跨物理切镜，只归属开始发声的镜头。未标定时省略这对字段，导出显示“未标定”。

~~~json
{"dialogue_id": "LINE-LOCK", "text": "门锁换过了。", "start": 2.5, "end": 4.0}
~~~

台词用中文或英文双引号，中文引号内可换行；非台词说明不加引号。引号原文放在实际镜头内，首镜之前不得夹入额外台词。计划时段不代表实测，声音参考文件长度也不代替对白预算。

### 素材绑定与画幅

`reference_bindings`包含`slot`与`asset_id`。静态用`@图片N`，动态用`@素材N`，N为正整数；每槽唯一，有独立参考声明，正文槽位集合须与绑定一致。绑定角色、场景、道具或声音时，同一ID须列入`asset_ids`；也可引用静态PROMPT作为参考图来源，不能引用动态PROMPT。

声明按素材职责写明继承范围。动态场景/故事板参考须禁止继承画面风格、光影、色彩，也不得正向继承这些属性。禁止句可同行或紧接声明续行；不能从其他素材借用排除项。具体写法见[公共规则](rule-authority.md)。

每条提示词须在末行唯一声明`--ar 比例`：T1/T3/T4为16:9，T2为3:4，其余模板（含T6C单帧关键帧）跟随项目主画幅。T5/T6/T6B采用同画幅3×3版式；T6/T6B使用`Shot #`行时，须按序包含1至9且已标定时间节点不回退、不超出所属分镜时长，引用的`物理镜头N`须存在于`shot.segments`。重复描述给出WARN，由人工确认是否为合法静止保持。

### 角色声音参考数据

`voices`保存视频模型的声音身份参考；设计、试听与返片方法见[声音资产规范](voice-reference-assets.md)。

| 字段 | 用途 |
|---|---|
| `id/revision/name` | 内部声音身份、版本与名称 |
| `character_id` | 所属CHAR；`null`用于独立旁白 |
| `description/language` | 稳定音色、语言口音和咬字 |
| `source/notes` | 来源与补充说明 |
| `status` | `planned`或`ready` |
| `audition` | `unreviewed/approved/needs_revision`，记录参考声音试听状态 |
| `audition_text`（可选） | 上游声音设计用的试听文案，与声音描述分开输入 |
| `master` | 母版`path/sha256/duration/transcript` |
| `references` | 模型副本列表：`id/model_id/path/sha256/duration/source_start/source_end/transcript` |

`planned`须为`master: null`、`references: []`，不能标记试听通过或分配音频槽。`ready`须有母版；试听未通过时给出WARN。样片文案和转写不进入`dialogues`或动态正文的台词引号，本镜表演仍由镜头正文决定。

副本ID在声音内唯一，裁剪区间落在母版内；副本时长与源区间长度允许0.05秒误差，不隐式变速。每个声音槽选择一条实际副本：

~~~json
{"slot": "@素材4", "asset_id": "VOICE-WANQING", "audio_reference_id": "wanqing-model-a"}
~~~

动态提示词使用声音绑定时须提供`audio_reference_profile`：`model_id`、`supports_voice_reference`、`max_files`、`max_file_duration`、`max_total_duration`、`formats`和能力依据`source`。副本模型须匹配，数量、时长、格式不超已知限制；未知限制用`null`、未知格式用空数组，QC提示待核实。

声明与角色行须指向同一声音归属，同一角色或旁白不同时绑定多个声音。静态提示词不能引用VOICE；明确声音身份的声明也不能绑定角色图片。通用`@素材N`最终须按实际平台的音频编号与上传方式适配。

## 依赖与修改

shots和prompts用`depends_on`保存直接依赖的ID、revision和SHA-256指纹：

| 实体 | 直接依赖 |
|---|---|
| shot | project、场景/角色/道具/节拍、实际执行的台词 |
| prompt | project、`asset_ids`、参考绑定及非空所属shot |

指纹包含实体全部字段，仅排除`depends_on`。上游改动会使下游失效；缺失、多余、重复、未知、成环及不匹配的依赖均报错。修改顺序为：修订源稿或上游 → 重做受影响内容并增版 → 显式capture → QC → 导出。capture只记录当前依赖，不代替内容修订。

`--previous`检查同项目的删除/改ID、版本回退和未增版的内容变更；不检查顶层数组重排。源文件不属于JSON快照，仅改源稿不会自动触发失效，须用`--source`对账。跨集公共资产通过`sync-assets`同步，命令见[本地工具](tools.md#数据修改)。

## 检查边界

完整JSON QC检查字段、引用、台词、时间、依赖和提示词；Markdown QC只检查独立提示词块。显式`--media-root`才检查声音本地文件、指纹与可读取WAV时长，不验证转写或音色。

故事因果、预算表、动作耗时、证据阅读、设计正文语义一致性及实际声音/口型效果由专业审阅和返片核对。程序QC、专业审阅和用户确认分别记录，创作草稿无需为送检强建完整JSON。
