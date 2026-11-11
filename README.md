# AI短剧制作技能包

本仓库提供五个创作子技能、静动态提示词模板，以及校验和导出制作文档的Python工具。交付包括故事开发与审阅文档、文学剧本、完整项目JSON和Markdown制作方案；实际图像、音频、视频生成与剪辑由外部工具完成。

制作主流程：选题与故事优化 → 剧本编写、审阅定稿 → 资产与节拍整理 → 八岗位分镜 → 静动态提示词 → JSON校验与导出。已有材料可以从相应阶段进入，阶段交付和回改见[制作流程](references/production-workflow.md)。

## 仓库导航

| 位置 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | Agent任务路由 |
| [sd-story-development](sd-story-development/SKILL.md) | 选题、故事优化、导演风格、证据审阅 |
| [sd-scriptwriter](sd-scriptwriter/SKILL.md) | 梗概、人物、大纲、场景剧本 |
| [sd-storyboard](sd-storyboard/SKILL.md) | 资产节拍、八岗位设计、镜头与声音 |
| [sd-static-assets](sd-static-assets/SKILL.md) | T1–T6/6B静态提示词 |
| [sd-dynamic-video](sd-dynamic-video/SKILL.md) | T7–T9动态提示词与声音脚本 |
| [references](references/) | 制作流程、公共规则、数据工具与尾约束写法 |
| [schemas/project.schema.json](schemas/project.schema.json) | 完整制作项目的字段契约 |
| [scripts](scripts/) | QC、依赖快照和Markdown导出 |
| [examples/demo](examples/demo/) | 两镜两句台词的项目及前期交接示例 |
| [tests](tests/) | Schema、数据关系、文本QC和导出回归测试 |

## 运行示例

Python 3.10+，脚本与测试只依赖标准库。在仓库根目录运行：

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --format json
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 scripts/qc_check.py output/demo --mode auto
python -B -X utf8 -m unittest discover -s tests -v
~~~

-B避免生成字节码缓存，-X utf8保持中文输入输出。参数、退出码、修改与快照操作见[项目数据与工具](references/project-data.md)。

导出示例：

~~~text
output/demo/
├── project.md             全局设定、节拍、原始台词、全局提示词和15列总表
├── SHOT-001_分镜.md       逐镜五章文档
├── SHOT-002_分镜.md
└── .drama-export.json     托管文件、指纹及过期文件清单
~~~

[前期交接示例](examples/demo/preproduction.md)说明源剧本与[项目JSON](examples/demo/project.json)的对应关系。示例保留unreviewed状态；导出文件按需重建，不纳入源文件。

## 维护约定

- 剧本及交接记录先更新，再修订受影响的制作数据、捕获依赖、运行QC和导出。
- 字段定义在Schema，跨模块约定在[公共规则](references/rule-authority.md)，提示词字段在各模块templates.md，工具行为在脚本。
- 前期文档由Agent/人工审阅；当前JSON校验要求完整shots和prompts。更多检查范围见[项目数据与工具](references/project-data.md)。

技能元数据为V18.1，数据契约为1.0；[_meta.json](_meta.json)记录原分发包1.0.5。前期开发方法参考director-screenwriter-master-1.0.5，已整理为本仓库内的独立参考文档。
