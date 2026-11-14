# AI短剧制作技能包

面向中文短剧从选题开发、剧本创作、八岗位分镜到静动态提示词交付的编排技能包，内置零第三方强依赖（Python 3.10+标准库）的项目数据管理、质量检查（QC）、Markdown导出与参考图无损切分脚本。

## 仓库目录与文件清单

| 路径 | 实际内容与职责 |
|---|---|
| `SKILL.md` | 顶层任务路由与执行约定 |
| `_meta.json` | 技能包发布元数据与版本标识 |
| `schemas/project.schema.json` | 项目JSON Schema（支持`1.0`与`1.1`单条角色声音参考结构） |
| `scripts/project_data.py` | 源剧本提取与骨架生成（`extract-script`）、跨集资产同步（`sync-assets`）、依赖快照捕获（`capture`）及项目关系校验 |
| `scripts/qc_check.py` | `project.json`与Markdown/纯文本提示词质量检查（含防串脸、跨镜光影、防连续参考代际噪点、单条声音参考与本地WAV校验） |
| `scripts/render_project.py` | 自动QC后导出`project.md`、逐镜五章文档`SHOT-ID_分镜.md`及`.drama-export.json`清单 |
| `scripts/slice_grid.py` | `T5`空间九视角、`T6`/`T6B`九宫格故事板（`--mode grid`）与`T1`角色设定图（`--mode t1`）无损PNG切分 |
| `references/production-workflow.md` | 六阶段交付链路、文件约定、交接映射与改稿回改顺序 |
| `references/project-data.md` | `project.json`顶层实体、校验规则、素材绑定与`depends_on`快照契约 |
| `references/rule-authority.md` | 跨模块规则编号（`R-*`）与唯一定义归属 |
| `references/scene-timing.md` | 整场时间预算、自然语速估算、视频模型起收音缓冲与分段规则 |
| `references/voice-reference-assets.md` | 单条角色声音参考（`VOICE-`）设计、`reference`音频登记与`@素材N`绑定规范 |
| `references/constraints.md` | 提示词末尾30–50字正向质量尾约束与衍生参考图防噪点写法 |
| `references/tools.md` | 四个本地CLI脚本的参数、行为与退出码说明 |
| `sd-story-development/` | 选题诊断、故事优化、导演风格与剧本证据审阅模块（`SKILL.md` + `references/`下4份参考） |
| `sd-scriptwriter/` | 梗概、人物、分场大纲与中文场景剧本模块（`SKILL.md` + `references/`下2份参考） |
| `sd-storyboard/` | 资产节拍整理、9B八岗位分镜设计与审阅模块（`SKILL.md` + `references/`下3份参考） |
| `sd-static-assets/` | `T1`–`T6`/`T6B`/`T6C`静态资产提示词与零代母图防噪点模块（`SKILL.md` + `references/`下2份参考） |
| `sd-dynamic-video/` | `T7`–`T9`动态视频提示词、原生声画脚本与单条角色音色绑定模块（`SKILL.md` + `references/`下2份参考） |
| `examples/demo/` | 《院门线索》Schema `1.0`示例（`preproduction.md`、`project.json`） |
| `examples/voice-reference/` | 《院门线索》Schema `1.1`单条角色声音参考示例（`README.md`、`preproduction.md`、`project.json`） |
| `tests/` | 覆盖Schema、数据关系、提示词解析、声音参考、防噪点、切图与导出的12个`unittest`测试文件 |

## 常用命令

在仓库根目录执行：

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --source examples/demo/preproduction.md
python -B -X utf8 scripts/qc_check.py examples/voice-reference/project.json --source examples/voice-reference/preproduction.md
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 -m unittest discover -s tests
~~~
