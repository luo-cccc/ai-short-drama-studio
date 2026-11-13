# AI短剧制作技能包

用于中文短剧的故事开发、剧本写作、分镜和静动态提示词制作，并提供项目JSON校验、Markdown导出及参考图切分工具。图片、声音和视频由外部工具生成；本仓库不接入媒体生成API，也不剪辑成片。

## 内容结构

| 位置 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | Agent任务入口与模块路由 |
| [sd-story-development/](sd-story-development/SKILL.md) | 选题、故事优化、导演风格与剧本审阅 |
| [sd-scriptwriter/](sd-scriptwriter/SKILL.md) | 梗概、人物、大纲与中文场景剧本 |
| [sd-storyboard/](sd-storyboard/SKILL.md) | 资产节拍、八岗位设计、镜头与声音规划 |
| [sd-static-assets/](sd-static-assets/SKILL.md) | T1–T6/6B/6C角色、道具、场景、故事板和单帧关键帧提示词 |
| [sd-dynamic-video/](sd-dynamic-video/SKILL.md) | T7–T9视频提示词及角色声音参考绑定 |
| [references/](references/production-workflow.md) | 共用制作规则、数据契约与工具说明 |
| [schemas/project.schema.json](schemas/project.schema.json) | 制作项目JSON字段契约，支持1.0及1.1 |
| [scripts/](scripts/) | 数据快照与同步、QC、文档导出、物理切图 |
| [examples/demo/](examples/demo/project.json) | 《院门线索》两段各5秒的完整数据与源稿交接 |
| [examples/voice-reference/](examples/voice-reference/README.md) | 1.1声音参考规划；声音为待制作状态 |
| [tests/](tests/) | 数据、提示词、声音参考、切图和导出回归测试 |

## 使用入口

制作流程为故事开发 → 剧本与审阅 → 资产节拍及整场预算 → 分镜 → 提示词与参考素材 → 校验和导出。已有材料可从对应阶段进入，局部任务交付所需范围。

- 做创作与制作：从[任务入口](SKILL.md)和[制作流程](references/production-workflow.md)开始。
- 编写项目JSON：查看[数据契约](references/project-data.md)及示例。
- 运行本地命令：查看[工具用法](references/tools.md)。
- 给视频模型准备角色音色：查看[声音参考资产](references/voice-reference-assets.md)。

## 本地运行

核心工具使用Python 3.10+标准库。切分额外图像格式时可选安装Pillow，具体支持范围见[切图工具](references/tools.md#切图)。在仓库根目录执行：

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --source examples/demo/preproduction.md
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 -m unittest discover -s tests
~~~

导出生成`project.md`、每镜`SHOT-ID_分镜.md`及托管清单`.drama-export.json`。`output/`是运行时生成目录，不保存源数据；导出后保留清单，供再次导出的覆盖检查使用。

项目JSON保存制作数据与依赖快照，Markdown是导出视图。回改先更新源稿及受影响内容，再捕获依赖、QC和导出。字段以Schema为准，跨模块规则见[公共规则](references/rule-authority.md)，提示词字段以各模块模板为准。
