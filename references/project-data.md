# 项目数据与本地工具

本页说明数据契约、依赖快照、QC和Markdown导出。字段形状以 [project.schema.json](../schemas/project.schema.json) 为准，完整示例见 [project.json](../examples/demo/project.json)，制作约定见 [rule-authority.md](rule-authority.md)。以下命令均在仓库根目录执行，需要Python 3.10+。

## 数据组织

项目使用UTF-8 JSON，可带BOM。不接受注释、尾逗号、重复键或NaN、Infinity等非有限数值；Schema中未声明的字段也会报错。

顶层必须包含`schema_version: "1.0"`、`project`和下表中的七个数组。`scenes`、`beats`、`shots`、`prompts`至少各有一项；`characters`、`props`、`dialogues`可以为空。各实体均有`id`和从1开始的整数`revision`；下表列出其余字段，嵌套结构和具体约束见Schema。

| 数据 | ID前缀 | 字段与用途 |
|---|---|---|
| project | PRJ- | `title`、`aspect_ratio`、`style`；画幅可选9:16、16:9、2.39:1 |
| characters | CHAR- | `name`、`description`、`voice`；角色外观与声线 |
| scenes | SCENE- | `name`、`description`；可复用场景 |
| props | PROP- | `name`、`description`；可复用道具 |
| beats | BEAT- | `scene_id`、`summary`、`character_ids`、`prop_ids`；按剧本顺序保存节拍 |
| dialogues | LINE- | `beat_id`、`speaker_id`、`kind`、`text`；数组定义台词执行顺序 |
| shots | SHOT- | `title`、`function`、`scene_ids`、`character_ids`、`prop_ids`、`beat_ids`、`duration`、`segments`、`static_prompt_ids`、`dynamic_prompt_id`、`design`、`audio`、`transitions`、`review`、`notes`、`depends_on` |
| prompts | PROMPT- | `template`、`shot_id`、`duration`、`asset_ids`、`reference_bindings`、`text`、`depends_on` |

这些字段均需写出，允许为空的值也不能省略。例如`notes`可为`""`，无配音时`lines`为`[]`，静态提示词的`duration`为`null`。ID后缀使用英文字母、数字、下划线和连字符，首字符须为字母或数字；全项目ID唯一，改名和排序不重发ID，内容变更增加`revision`。

## 前期交接与数据边界

此JSON用于完整制作数据，阶段草稿和源稿交接仍使用Markdown，入口见 [制作全流程](production-workflow.md) 和 [交接示例](../examples/demo/preproduction.md)。脚本不解析这些侧文档，也不追踪其他项目目录或跨集设定；只修改源稿不会触发JSON依赖失效。`review.status`记录`unreviewed`、`needs_revision`或`approved`并用于导出显示，未审查状态不阻止QC或导出。工具生成的是数据和文档，不生成或核验图像、音频、视频文件；JSON检查、专业审查和用户确认分别记录。

## 关系校验

### 节拍、分镜和提示词

每个beat至少被一个shot的`beat_ids`认领，可拆到多个shot；每个认领分镜都须登记该节拍的场景、角色和道具。检查验证ID覆盖，剧情行动是否完整呈现仍需按制作规范审阅。

每个shot至少引用一条静态提示词，并通过`dynamic_prompt_id`引用唯一归属本镜的动态提示词。静态模板为T1–T6及T6B，动态模板为T7–T9。静态提示词的`shot_id`可为`null`供全局复用，或指向登记它的本镜；动态提示词须指向本镜、时长相同，且`asset_ids`包含本镜全部角色、场景和道具。

`design`是由`role`、`knowledge`、`decision`组成的八项数组，`director`、`camera`、`lighting`、`action`、`staging`、`dialogue`、`sound`、`vfx`各出现一次。`audio`包含`ambience`、`music`和`effects`，`transitions`包含`incoming`和`outgoing`，`review`包含`design_id`和`status`；`design_id`使用`9B-`前缀。

### 台词与局部时间

`dialogues.kind`为`dialogue`、`os`或`narration`；只有`narration`允许`speaker_id: null`。指定的说话角色须登记在所属节拍及执行该台词的分镜中。

`segments`的每项包含`index`、`start`、`end`、`description`和`lines`；`lines`每项包含`dialogue_id`和实际执行的`text`。依次遍历shots、segments、lines时，全部原台词须各出现一次，且顺序与`dialogues`数组相同。文本对账先做Unicode NFC归一化，再忽略Unicode标点与空白，保留文字、数字和其他符号；标点格式仍单独参加文本QC。

每个shot的`duration`为5–30秒，以0.1秒为步长。其segments使用本shot的局部时间：序号从1连续递增，首段从0开始，相邻起止相接，每段时长为正，最后结束等于`duration`。动态提示词采用`镜头1（0.0-5.0s）：`格式，每个起止数值恰好一位小数；项目QC还会对账镜头数量、时间及各镜头引号内的台词。

台词可用中文双引号或英文双引号，中文引号内允许换行。非台词内容不要加引号，以免被识别为额外台词。管理词扫描只豁免起始于合法镜头行，或镜头内带“说：”“OS：”“NAR：”等明确引导的引号台词；静态提示词、动态前置说明和尾部说明中的引号不享有此豁免。

### 素材绑定与画幅

`reference_bindings`每项包含`slot`和`asset_id`。静态提示词使用`@图片N`，动态使用`@素材N`，N为正整数；槽位在当前提示词内唯一，正文出现的槽位集合须与绑定集合一致。绑定角色、场景或道具时，该ID也须列入`asset_ids`；还可绑定静态PROMPT ID作为参考图的逻辑来源，不能绑定动态提示词。

每个用到的槽位须有独立参考声明，例如`@素材1 参考场景空间布局。禁止继承画面风格、光影、色彩。`。禁止句可同处一行，或紧随声明另起协议续行，中间允许空行；遇到其他正文或下一条素材声明即停止关联。动态场景、故事板、故事分镜图和调度图参考须完整禁止继承画面风格、光影、色彩，正向继承这些属性也会报错。检查按声明主语区分场景与角色、道具；使用明确主语和协议句式，具体继承范围见 [R-REF-001](rule-authority.md)。

项目QC要求每条提示词在末行唯一声明`--ar 比例`：

| 模板 | 外画幅 |
|---|---|
| T1、T3、T4、T6、T6B | 16:9 |
| T2 | 3:4 |
| T5、T7、T8、T9 | `project.aspect_ratio` |

图板内部九格的画幅由提示词文字表达，当前检查不读取实际图像比例。

## 修改与快照

shots和prompts的`depends_on`保存直接依赖的`id`、`revision`和SHA-256 `fingerprint`：

| 派生实体 | 必须保存的直接依赖 |
|---|---|
| shot | project、引用的场景/角色/道具/节拍、segments实际使用的台词 |
| prompt | project、`asset_ids`、素材绑定实体、非null的所属shot |

指纹包含实体全部字段及revision，只排除`depends_on`，因此名称、备注、审查状态的修改也会影响下游。缺失、多余、重复、未知、成环或不匹配的依赖会报错，失效会沿派生实体的引用关系向下游传播。

### capture：显式记录已完成内容的依赖

首次建立完整数据时，可先将每条shot和prompt的`depends_on`写为`[]`，其他字段仍须完整，然后捕获全部shot和prompt。CLI必须至少传一次`--entity`，重复此参数选择多个实体，没有省略参数即全选的模式。PowerShell可从JSON收集全部ID：

~~~powershell
$project = Get-Content -Raw -Encoding utf8 project.draft.json | ConvertFrom-Json
$captureArgs = @()
foreach ($entity in (@($project.shots) + @($project.prompts))) {
    $captureArgs += @('--entity', $entity.id)
}
python -B -X utf8 scripts/project_data.py capture project.draft.json @captureArgs --output project.captured.json
python -B -X utf8 scripts/qc_check.py project.captured.json
~~~

后续修改先增版上游实体并重做受影响内容，再选择已完成的分镜与提示词。例如：

~~~powershell
python -B -X utf8 scripts/project_data.py capture project.json --entity SHOT-001 --entity PROMPT-BOARD-001 --entity PROMPT-VIDEO-001 --output output/project.updated.json
~~~

capture输出完整项目副本，只刷新所选实体的快照。它检查字段形状和所选实体的依赖，不执行完整项目QC，不改写创作内容或revision，也不会自动选入其他实体。若所选提示词仍依赖已失效的分镜或静态提示词，须先完成上游修改并将相应实体一并选入。`--output`必须是不存在的新文件，可自动创建父目录；完成后对输出文件运行QC。

### --previous：与同一项目的基线比较

~~~powershell
python -B -X utf8 scripts/qc_check.py project.json --previous project.accepted.json
~~~

旧文件先做字段形状检查，并要求`project.id`相同。比较会报告旧实体删除或改ID、revision回退，以及实体内容修改但revision未增加；新增实体允许存在。仅改`depends_on`不计为内容修改，顶层数组重排也不由基线比较检查，当前项目仍须通过自身的顺序与关系校验。验收基线由维护者保存，工具不分配ID或维护长期历史。

## QC命令

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --format json
python -B -X utf8 scripts/qc_check.py output/demo --mode auto
python -B -X utf8 scripts/qc_check.py prompt.txt --mode dynamic --duration 10
~~~

| 输入或选项 | 实际行为 |
|---|---|
| `.json`文件 | 自动按项目检查：字段、关系、快照及每条提示词 |
| `--project` | 强制将文件或stdin作为项目JSON读取 |
| 目录 | 只递归扫描`.md`和`.txt`，跳过名为`SKILL.md`的文件；目录内JSON不检查，须分别传入文件 |
| 不传路径 | 从stdin读取；项目JSON必须加`--project`，否则按文本检查 |
| `--mode auto/static/dynamic` | 用于文本；auto优先采用块template，再结合标题、代码块语言和正文判断 |
| `--duration 10` | 文本动态块的规定时长，须为5–30秒的有限数值；覆盖块元数据，并与任务声明和镜头终点对账 |
| `--previous 文件` | 仅用于项目JSON，执行上节的基线比较 |
| `--format text/json` | 默认为可读文本；JSON输出包含`ok`、`checked`、`skipped`、`results` |

从文件演示stdin项目输入时，PowerShell可调用cmd的输入重定向：

~~~powershell
cmd /c "python -B -X utf8 scripts/qc_check.py --project --format json < project.json"
~~~

项目JSON始终使用每条记录的template和duration，`--mode`或`--duration`不覆盖它们。JSON输出中的`checked`是检查结果记录数：项目模式包含一条项目结果及各提示词结果，不是文件数。

### Markdown与纯文本

Markdown逐个检查独立提示词代码块，不扫描块外的规划标题、说明和表格。支持`text`、`txt`、`prompt`、`static`、`dynamic`语言块，以及能按元数据、标题模板或正文识别的无语言块；JSON、Python等代码块跳过，提示词块未闭合会报错。

块前可写`<!-- prompt id=PROMPT-VIDEO-001 template=T9 duration=5.0 -->`指定身份、模板和时长，元数据紧邻代码块，可间隔空行。导出器自动写入这些元数据。无围栏的`.txt`或stdin按纯提示词检查；无围栏的`.md`只有在不含Markdown标题且能识别为提示词时才检查，否则作为规划文档跳过。请扫描交付目录，而非含模板占位符的规则库。

### 诊断与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 无ERROR；只有WARN也返回0 |
| 1 | 有ERROR；QC的空目录或全部跳过也返回1 |
| 2 | 命令参数错误，如缺少必填参数或非法`--duration` |

三个CLI均采用上述成功、失败和参数错误退出码。QC的WARN包括风格段识别、字数、抽象情绪等文字启发式提示，应按诊断复核；无ERROR不等于全部制作规则或画面质量已验收。

## 导出与测试

### render_project：导出托管Markdown

~~~powershell
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
~~~

导出器先运行完整项目QC，有ERROR时不写文件。QC的WARN不阻止导出，也不会在导出命令中逐条展示，需单独运行QC查看。导出命令没有`--previous`选项；需要基线比较时，先对同一输入文件运行带`--previous`的QC。

| 输出 | 内容 |
|---|---|
| `project.md` | 全局设定、节拍摘要、按dialogues数组顺序列出的原始台词、全局静态提示词和15列总分镜表；字段见 [总分镜表字段](../sd-storyboard/SKILL.md#总分镜表字段) |
| `SHOT-ID_分镜.md` | 每镜五章及独立提示词代码块，结构见 [导出交付](../sd-storyboard/SKILL.md#导出交付) |
| `.drama-export.json` | 项目归属、托管文件指纹及过期文件清单；重复导出时须保留 |

导出不修改源JSON和依赖快照。重复导出可更新未被手改的托管文件；同名非托管文件、手工改过的目标文件或属于另一项目的导出目录会阻止覆盖。手改内容须先核对合并回JSON，或使用新目录导出。

不再属于当前项目的旧文件会保留，`obsolete_files`持续提示，直到文件被人工删除或重新纳入项目。`obsolete_file_fingerprints`保留其原导出指纹，恢复旧镜头时仍按该指纹保护手改内容。旧版清单可以读取；若旧清单中的过期文件没有原指纹，恢复时不会直接覆盖，需先核对合并或换用新目录。

### 本地测试

~~~powershell
python -B -X utf8 -m unittest discover -s tests -v
~~~

正式脚本与测试只依赖Python标准库。测试覆盖Schema字段约束、引用、台词与时间对账、依赖失效、文本QC和导出保护，可用示例验证数据到文档的链路。
