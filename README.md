# AI短剧制作技能包

本仓库包含四个创作子技能、提示词模板，以及校验和导出制作文档的Python工具。交付对象是剧本、结构化项目数据和Markdown制作方案；仓库没有媒体生成API、任务队列或剪辑引擎。

## 内容导航

| 位置 | 用途 |
|---|---|
| [SKILL.md](SKILL.md) | Agent入口：按用户材料选择制作环节 |
| [sd-scriptwriter](sd-scriptwriter/SKILL.md) | 大纲、人物、场景剧本 |
| [sd-storyboard](sd-storyboard/SKILL.md) | 剧情拆分、八岗位设计、镜头和声音规划 |
| [sd-static-assets](sd-static-assets/SKILL.md) | T1–T6/6B静态提示词和故事板模板 |
| [sd-dynamic-video](sd-dynamic-video/SKILL.md) | T7–T9动态提示词、配音与音效脚本文本 |
| [references/rule-authority.md](references/rule-authority.md) | 规则适用范围与优先级 |
| [references/project-data.md](references/project-data.md) | 数据关系、快照、命令及工具边界 |
| [schemas/project.schema.json](schemas/project.schema.json) | 完整制作项目的字段契约 |
| [scripts](scripts/) | 项目校验、依赖快照、Markdown导出 |
| [examples/demo/project.json](examples/demo/project.json) | 两镜、两句台词的可运行数据示例 |
| [tests](tests/) | Schema、引用、台词、快照、文本QC和导出回归测试 |

## 运行示例

使用Python 3.10或以上，正式脚本只依赖标准库。以下命令均在仓库根目录运行；-B防止写入字节码缓存，-X utf8用于保持中文输入输出。

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --format json
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 scripts/qc_check.py output/demo --mode auto
~~~

生成目录包含：

~~~text
output/demo/
├── project.md             全局设定、剧本节拍、全局提示词、15字段总分镜表
├── SHOT-001_分镜.md       第一镜固定五章交付
├── SHOT-002_分镜.md       第二镜固定五章交付
└── .drama-export.json     导出文件及指纹清单
~~~

示例是数据链路演示，review.status保留unreviewed，没有实际图片、视频或音频。生成的Markdown与清单不纳入源文件，按需重建。

运行回归测试：

~~~powershell
python -B -X utf8 -m unittest discover -s tests -v
~~~

## 使用边界

- 当前JSON契约要求完整制作数据，包含非空的shots和prompts。独立剧本与阶段草稿可先用Markdown审阅，尚不能作为完整项目通过JSON校验。
- JSON QC核对字段、ID引用、节拍认领、台词文字与顺序、时间及依赖快照。剧情是否在画面中成立、空间表演和审美质量仍需制作人员审阅。
- Markdown/文本QC逐提示词检查格式，不回查剧本、资产实体或历史版本。目录扫描只读取.md/.txt，项目JSON需要直接指定文件。
- 审查状态由制作人员维护，QC和导出器不会因为状态为unreviewed而拒绝导出。用户约定的确认点由制作流程执行。
- 导出前运行完整项目QC。已有输出若被手工修改，或目标含非托管同名文件，导出器会拒绝覆盖；已不再使用的旧镜头文件会保留并提示人工处理。

详细选项、修改与快照流程见[项目数据说明](references/project-data.md)；提示词结构以对应模块的模板文件为准。

## 维护约定

修改创作内容先更新项目JSON，再校验和导出。修改字段先更新Schema，修改跨模块规范先更新规则权威表，再同步模板、代码与测试。依赖快照只在相关内容完成修订后显式重建。

技能元数据版本为V18.0；[_meta.json](_meta.json)记录原分发包1.0.5的来源，不参与运行，也不代表当前脚本的独立发布版本。
