# 项目数据与本地工具

字段结构以 [project.schema.json](../schemas/project.schema.json) 为准，最小完整示例见 [project.json](../examples/demo/project.json)。本页说明数据关系与当前脚本行为；制作规范见 [rule-authority.md](rule-authority.md)。

## 数据组织

当前schema_version为1.0，顶层包括project、characters、scenes、props、beats、dialogues、shots、prompts。所有集合实体与project均有id和revision，前缀依次为PRJ、CHAR、SCENE、PROP、BEAT、LINE、SHOT、PROMPT。

| 数据 | 用途与关系 |
|---|---|
| project | 项目名称、画幅、共享风格 |
| characters / scenes / props | 角色、场景和道具的可复用定义 |
| beats | 剧本节拍及对应场景、角色、道具；数组按剧本顺序保存 |
| dialogues | 原始台词、类型、说话者及所属节拍；数组定义台词执行顺序 |
| shots | 节拍认领、资产引用、时长、物理镜头segments、八岗位design、声音、衔接和审查记录 |
| prompts | T1–T9或T6B提示词、所属分镜、资产与局部素材位绑定 |

ID创建后保持稳定，改名或排序不重发ID；内容变更增加revision。脚本检查当前ID唯一，可用历史基线检查增版。仓库没有ID分配器或历史数据库，长期不复用已删除ID需要项目维护者保证。

当前Schema要求shots和prompts非空，适合完整制作数据。独立文学剧本、全局设定和阶段草稿可先保存Markdown；没有自动将既有Markdown解析成完整项目的迁移工具，也没有分阶段JSON校验模式。

## 关系校验

每个beat至少被一个shot认领，可拆到多个shot；分镜必须承接节拍登记的场景、角色和道具。此检查验证ID覆盖，不能判断自然语言动作或画面是否已经完整呈现剧情。

segments由index、start、end、description和lines组成。每条lines关联dialogue_id及实际台词text，要求所有原台词各执行一次、顺序一致。对账忽略Unicode标点与空白，保留文字、数字及其他符号；动态提示词对应镜头中引号内的台词，还会与segments.lines再次对账。非台词内容不要使用引号，避免被当作额外配音。

分镜duration为5–30秒。segments的数值最多一位小数，从零开始、连续递增且与总时长一致；实际动态提示词必须使用镜头1（0.0-5.0s）：这样的时间戳，每个起止数值恰好一位小数。

reference_bindings把当前提示词内的@图片N或@素材N绑定到角色、场景、道具ID，也可绑定静态PROMPT ID作为参考图片的逻辑来源。正文槽位与绑定集合必须一致；这不表示图片文件已生成或存在。模板T1/T3/T4/T6/T6B的外画幅固定16:9，T2为3:4，其余采用项目画幅。图板内部九格画幅仍由提示词文字表达，脚本不检查实际图像比例。

八岗位design必须各出现一次。review记录design_id与unreviewed、needs_revision或approved状态；状态用于导出显示，脚本不执行审批门控。专业审查和用户确认由制作流程完成。

## 修改与快照

shots和prompts通过depends_on保存直接依赖的id、revision和SHA-256指纹。指纹包含实体全部字段（含revision），只排除depends_on本身，因此名称、备注、审查状态等字段变化也会触发依赖更新。

- 分镜依赖项目设定、引用的场景/角色/道具/节拍及实际使用的台词。
- 提示词依赖项目设定、asset_ids、素材绑定实体及所属分镜。
- 缺失、多余、重复、未知、成环或内容不匹配的依赖会报错；失效会沿下游传播。

先修改并增版上游实体，再重做受影响的分镜与提示词。确认内容完成后，显式记录这些实体的当前依赖；多个实体可重复传入--entity：

~~~powershell
python -B -X utf8 scripts/project_data.py capture examples/demo/project.json --entity SHOT-001 --entity PROMPT-BOARD-001 --entity PROMPT-VIDEO-001 --output output/project.updated.json
~~~

--output必须指向不存在的新文件，工具不会原地覆盖输入。capture只检查字段形状和所选实体的依赖，不执行完整项目QC、不修改revision、不改写创作内容，也不批准审查；捕获后仍需运行QC。重捕指纹只能记录当前状态，不能证明实际修订正确。

与上次验收的同一项目比较：

~~~powershell
python -B -X utf8 scripts/qc_check.py project.json --previous project.accepted.json
~~~

--previous检查旧实体删除或改ID、revision回退、实体内容变更未增版；它不维护长期历史，不检查顶层数组重排，也不替代保留验收基线。

## QC命令

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --format json
python -B -X utf8 scripts/qc_check.py output/demo --mode auto
~~~

| 选项 | 当前行为 |
|---|---|
| 文件或目录 | .json文件直接作为项目检查；目录只递归.md/.txt并跳过SKILL.md |
| 不传路径 | 从stdin读取；JSON需另加--project |
| --mode auto/static/dynamic | 仅用于文本/Markdown；auto按块元数据、标题和内容判断模式 |
| --duration 10 | 仅用于文本/Markdown，覆盖块元数据时长；仍检查任务声明是否与之相符 |
| --previous 文件 | 仅用于JSON项目；与旧项目实体对比 |
| --format text/json | 输出可读诊断或含ok/checked/skipped/results的JSON |

JSON分支使用每条记录的template与duration，不使用--mode或--duration覆盖。Markdown以独立提示词代码块为单位读取，不扫描代码块外的规划标题和表格；支持text/txt/prompt/static/dynamic及可识别的无语言块，跳过JSON/Python等代码块。导出器在块前写入prompt元数据注释，因此混合文档可逐块识别。没有围栏的普通文本也可直接检查；有标题的Markdown规划文档会跳过。

ERROR使退出码为1；只有WARN返回0，仍需人工复核。空目录或全部跳过返回1，参数错误返回2。⑤风格段、尾约束长度、抽象情绪和部分参数采用文字启发式提示，不代表完整六层或画面质量已验收。模板源文件含写作占位，不应作为实际提示词通过QC；请扫描生成交付目录，不要扫描整个规则库来判断成品合格。

## 导出与测试

~~~powershell
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 -m unittest discover -s tests -v
~~~

导出器先执行完整项目QC，存在ERROR时不写文件；WARN不阻止导出且不会在导出命令中逐条展示，需要单独运行QC查看。文件包括project.md全局文档、每镜的SHOT-ID_分镜.md以及.drama-export.json管理清单。分镜五章为设计思维、静态提示词、动态提示词、配音音效、素材位与资产清单。提示词单独代码块，元数据留在块外。

重复导出可更新未被手改的托管文件；同名非托管文件或手工改过的文件会阻止覆盖。已经不在项目中的旧镜头文件保留，并写入导出清单的obsolete_files提示处理。导出不生成图像、音频或视频，不检查媒体文件存在，也不更新源JSON和快照。

运行环境为Python 3.10+，正式脚本与测试只依赖标准库。示例审查状态为unreviewed，用于验证数据到文档的链路。测试覆盖字段约束、引用、台词、时间、依赖失效、文本QC与导出行为，不包含外部模型或成片效果测试。
