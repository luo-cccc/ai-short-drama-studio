# AI短剧制作技能包

用于中文短剧的故事开发、剧本写作、八岗位分镜和静动态提示词制作，提供项目JSON校验、依赖快照同步、Markdown文档导出及参考图切分脚本。

## 仓库结构

| 路径 | 说明 |
|---|---|
| `SKILL.md` | 顶层任务入口与模块路由 |
| `_meta.json` | 技能包元数据与版本信息 |
| `schemas/project.schema.json` | 项目JSON Schema（支持`1.0`与`1.1`） |
| `scripts/project_data.py` | 源剧本提取、草稿骨架生成、共享资产同步、依赖快照捕获与项目校验 |
| `scripts/qc_check.py` | 项目JSON与Markdown/纯文本提示词质量检查 |
| `scripts/render_project.py` | 校验并导出`project.md`、逐镜`SHOT-ID_分镜.md`及`.drama-export.json` |
| `scripts/slice_grid.py` | T5空间九视角、T6/T6B九宫格故事板及T1角色设定图无损切分 |
| `references/production-workflow.md` | 故事开发到校验导出的阶段交付、交接表与回改顺序 |
| `references/project-data.md` | `project.json`实体、字段关系、素材绑定与依赖快照规则 |
| `references/rule-authority.md` | 跨模块规则编号（`R-*`）与定义归属 |
| `references/scene-timing.md` | 整场时间预算与制作片段拆分规则 |
| `references/voice-reference-assets.md` | 角色声音设计、母版、模型投喂副本与音频槽绑定规范 |
| `references/tools.md` | 四个本地CLI脚本的参数、输出与退出码说明 |
| `references/constraints.md` | 提示词30–50字正向尾约束写法 |
| `sd-story-development/` | 选题、故事优化、剧本证据审阅与导演风格模块（含`SKILL.md`及4份参考） |
| `sd-scriptwriter/` | 梗概、人物、大纲与中文场景剧本模块（含`SKILL.md`及2份参考） |
| `sd-storyboard/` | 资产节拍、9B八岗位分镜与审阅模块（含`SKILL.md`及3份参考） |
| `sd-static-assets/` | T1–T6/T6B/T6C静态资产提示词模块（含`SKILL.md`及2份参考） |
| `sd-dynamic-video/` | T7–T9动态视频提示词与声音脚本模块（含`SKILL.md`及2份参考） |
| `examples/demo/` | 《院门线索》1.0完整项目数据（`project.json`）与前期交接文档（`preproduction.md`） |
| `examples/voice-reference/` | 《院门线索》1.1声音参考规划示例（`README.md`、`preproduction.md`、`project.json`） |
| `tests/` | Schema、数据关系、提示词QC、声音参考、切图与导出的单元测试套件 |

## 快速开始

核心脚本仅依赖Python 3.10+标准库（切分非标准PNG或JPEG/WebP时可选安装Pillow）。在仓库根目录执行：

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --source examples/demo/preproduction.md
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 -m unittest discover -s tests
~~~

- **创作与制作编排**：从[SKILL.md](SKILL.md)和[制作流程](references/production-workflow.md)进入对应阶段。
- **数据结构与改稿**：参考[项目数据契约](references/project-data.md)与[公共规则](references/rule-authority.md)。
- **命令行工具**：参考[本地工具说明](references/tools.md)。
