# 本地工具说明

`scripts/`下的四个CLI脚本仅依赖Python 3.10+标准库（`slice_grid.py`处理非标准PNG或JPEG/WebP时可选安装Pillow）。在仓库根目录使用`python -B -X utf8`执行。

## 1. 质量检查：`scripts/qc_check.py`

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --source examples/demo/preproduction.md
python -B -X utf8 scripts/qc_check.py output/demo --mode auto
python -B -X utf8 scripts/qc_check.py prompt.txt --mode dynamic --duration 10
~~~

| 参数 | 说明 |
|---|---|
| `target` | `.json`项目文件、`.md`/`.txt`文件或目录；省略时从`stdin`读取 |
| `--project` | 将输入强制作为`project.json`检查（`.json`后缀自动启用） |
| `--mode auto\|static\|dynamic` | 文本/Markdown提示词检查模式（默认`auto`） |
| `--duration` | 显式指定单条动态提示词的规定时长（5–30秒） |
| `--source` | （仅项目JSON）与源剧本或`preproduction.md`对账台词文本、说话者、类型及`BEAT->SHOT`/`LINE`映射 |
| `--previous` | （仅项目JSON）与旧版`project.json`比较，检查实体删改、版本回退及修改未增版 |
| `--shared-assets` | （仅项目JSON）校验当前项目的角色、场景、道具、声音及全局静态提示词是否与共享资产库一致 |
| `--media-root` | （仅项目JSON）检查`voices`登记的本地音频文件存在性、SHA-256指纹及WAV实测时长 |
| `--format text\|json` | 输出可读文本或`{"ok", "checked", "skipped", "results"}` JSON结构 |

- **Markdown扫描规则**：仅扫描`text`/`txt`/`prompt`/`static`/`dynamic`代码块及带`<!-- prompt id=... template=... duration=... -->`元数据的代码块；自动跳过`json`/`python`/`wan`等代码块及`SKILL.md`。

## 2. 项目数据管理：`scripts/project_data.py`

~~~powershell
python -B -X utf8 scripts/project_data.py capture project.draft.json --all --output project.json
python -B -X utf8 scripts/project_data.py capture project.json --stale --in-place
python -B -X utf8 scripts/project_data.py sync-assets ep02/project.json --from shared/assets.json --in-place
python -B -X utf8 scripts/project_data.py extract-script examples/demo/preproduction.md
python -B -X utf8 scripts/project_data.py extract-script examples/demo/preproduction.md --scaffold --output project.draft.json
~~~

| 子命令 | 主要参数 | 说明 |
|---|---|---|
| `capture` | `--all` \| `--stale` \| `--entity ID`（三选一），`--output PATH` \| `-i/--in-place` | 计算并写入`shots`与`prompts`的`depends_on`依赖快照；指定下游`--entity`时其失效上游也须一并选入 |
| `sync-assets` | `--from PATH`，`--include-new`，`--output PATH` \| `-i/--in-place` | 从共享资产JSON或上游项目同步同ID的角色、场景、道具、声音及全局静态提示词（`--include-new`并入新资产） |
| `extract-script` | `source`，`--scaffold`，`--output PATH` | 从源剧本或`preproduction.md`提取动作、台词与映射；加`--scaffold`直接生成可通过Schema与源稿校验的`project.json`草稿骨架 |

- `--output`拒绝覆盖已存在文件；`--in-place`使用同目录临时文件原子替换，写入失败时保留原文件。

## 3. 文档导出：`scripts/render_project.py`

~~~powershell
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 scripts/render_project.py project.json --media-root media --output output/project
~~~

导出前自动执行完整项目QC（含`--media-root`音频检查），存在`ERROR`时拒绝写入。导出目录包含：
- `project.md`：项目全局设定、角色声音参考资产库（如有）、剧本节拍与原始台词、全局静态提示词及15列总分镜表。
- `SHOT-ID_分镜.md`：每镜五章文档（第一章分镜设计思维、第二章静态资产描述词、第三章动态视频描述词、第四章配音与音效脚本、第五章素材位对照与资产清单）。动态提示词配置了`audio_reference_profile`时按目标模型输出单块；未配置时同时输出即梦Seedance全模态块（`text`）与万相Wan纯视觉转换块（`wan`）。
- `.drama-export.json`：记录导出文件的SHA-256指纹与已移除分镜的过期文件（`obsolete_files`）。重复导出时拒绝覆盖非托管文件或被手工修改的交付文件。

## 4. 图像切分：`scripts/slice_grid.py`

~~~powershell
python -B -X utf8 scripts/slice_grid.py storyboard.png --output output/slices/SHOT-001 --mode grid
python -B -X utf8 scripts/slice_grid.py scene_views.png --output output/slices/SCENE-GATE --mode grid --grid-kind spatial
python -B -X utf8 scripts/slice_grid.py character_t1.png --output output/slices/CHAR-WANQING --mode t1
~~~

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--mode grid\|t1` | `grid` | `grid`切分等分网格（默认3×3）；`t1`切分角色设定图（左55%全身三视图+右45%四格头像） |
| `--grid-kind storyboard\|spatial` | `storyboard` | `storyboard`在清单标记`first_frame`/`last_frame`/`middle_keyframes`；`spatial`（T5）标记`space_views` |
| `--rows` / `--cols` | `3` / `3` | `grid`模式的行列数 |
| `--trim` | `0.015` | 每格四边内缩去框线比例（范围`[0.0, 0.25)`） |
| `--prefix` | `Shot` | `grid`模式输出文件名前缀 |

- **输出文件**：
  - `grid`模式：`<prefix>_01.png`至`<prefix>_09.png`及`slice-manifest.json`。
  - `t1`模式：`char_full_3views.png`（左区整体）、`char_body_01_front.png`、`char_body_02_side90.png`、`char_body_03_back.png`（三张全身）及`char_head_01_front.png`、`char_head_02_angle45.png`、`char_head_03_profile90.png`、`char_head_04_expression.png`（四张面部特写）及`slice-manifest.json`。
- 标准库直接支持非隔行8/16位灰度、RGB、RGBA PNG并保留透明与色彩块（`tRNS`/`gAMA`/`cHRM`/`iCCP`/`sRGB`/`sBIT`/`pHYs`）；隔行PNG、索引色PNG及JPEG/WebP回退使用Pillow；动画PNG（含`acTL`）直接报错，需先提取静帧。拒绝覆盖已有文件或源图。

## 退出码

四个脚本统一使用：`0`成功（或仅有`WARN`）、`1`校验或执行失败、`2`命令行参数错误。
