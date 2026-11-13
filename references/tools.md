# 本地工具

四个CLI使用Python 3.10+标准库；切图的部分格式可选Pillow。以下命令在仓库根目录运行，`-B`避免字节码缓存，`-X utf8`保持中文输入输出。数据字段见[项目数据契约](project-data.md)，完整参数用各脚本`--help`查看。

## 校验

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/demo/project.json --source examples/demo/preproduction.md
python -B -X utf8 scripts/qc_check.py output/demo --mode auto
python -B -X utf8 scripts/qc_check.py prompt.txt --mode dynamic --duration 10
~~~

| 输入或选项 | 行为 |
|---|---|
| `.json`或`--project` | 完整项目QC：校验Schema、依赖快照、台词与时间轴、视觉/声音参考槽归属防串脸、不可变五官骨相DNA与跨镜声线一致性 |
| 目录 | 递归扫描`.md/.txt`，跳过`SKILL.md`；目录内JSON须另行检查 |
| 无路径 | 读取stdin；项目输入须加`--project` |
| `--mode auto/static/dynamic` | 文本检查模式 |
| `--duration` | 文本动态块的规定时长，5–30秒；覆盖块元数据 |
| `--source` | 对账源稿台词、身份、顺序和定位映射 |
| `--previous` | 与同项目旧JSON比较版本与内容 |
| `--shared-assets` | 检查公共角色、场景、道具、声音和全局静态提示词 |
| `--media-root` | 检查登记声音文件的存在、SHA-256及可读取WAV时长 |
| `--format text/json` | 可读文本或`ok/checked/skipped/results`结构 |

`--source/--previous/--shared-assets/--media-root`仅用于项目JSON。`checked`为结果记录数，包含项目结果及逐提示词结果，不是文件数。非WAV音频只检查文件与指纹，工具不试听、上传或验证平台能力。

### Markdown与纯文本

Markdown扫描独立的`text/txt/prompt/static/dynamic`代码块及可识别的无语言提示词块，跳过JSON/Python等代码；未闭合提示词块报错。规划标题、说明和表格不参加文本QC，导出的`wan`兼容草稿也不作为原始提示词检查。

导出器在块前写入`<!-- prompt id=PROMPT-VIDEO-001 template=T9 duration=5.0 -->`元数据。识别优先级为块元数据、最近有效标题、块语言和正文；普通摄影续行不会增加物理镜头。无围栏`.txt`和stdin按纯提示词处理；带标题或不能识别为提示词的无围栏`.md`作为规划文档跳过。应扫描交付目录，规则库中的模板占位符不是成品。

## 数据修改

~~~powershell
python -B -X utf8 scripts/project_data.py capture project.draft.json --all --output project.json
python -B -X utf8 scripts/project_data.py capture project.json --stale --in-place
python -B -X utf8 scripts/project_data.py sync-assets ep02/project.json --from shared/assets.json --in-place
python -B -X utf8 scripts/project_data.py extract-script examples/demo/preproduction.md
python -B -X utf8 scripts/project_data.py extract-script examples/demo/preproduction.md --scaffold --output project.draft.json
~~~

- `capture`：`--all/--stale/--entity ID`三选一；`--entity`可重复。先完成内容修订，再捕获依赖。选择下游时，其失效上游也须完成并一同选入，或使用`--stale`。capture不运行完整QC、不修改创作内容或revision。
- `sync-assets`：同步当前项目已收录的同ID角色、场景、道具、声音及全局静态提示词；`--include-new`并入新资产。重复ID或全局动态模板被拒绝。同步后重做受影响内容、捕获依赖并QC。
- `extract-script`：提取动作、台词及映射骨架，默认输出到stdout，可用`--output`保存；加`--scaffold`可一键生成含资产、节拍、台词、分镜八岗位占位及依赖快照的`project.json`初始草稿骨架，后续在此基础上精修设计与提示词正文。

capture和sync须选择`--output`新文件或`--in-place/-i`。新文件不能覆盖已有路径；原地更新在完整编码后通过同目录临时文件替换，失败保留原文件。

## 导出

~~~powershell
python -B -X utf8 scripts/render_project.py examples/demo/project.json --output output/demo
python -B -X utf8 scripts/render_project.py project.json --media-root media --output output/project
~~~

| 文件 | 内容 |
|---|---|
| `project.md` | 全局设定、声音资产、节拍、原始台词、静态提示词及15列总分镜表 |
| `SHOT-ID_分镜.md` | 设计、静态提示词、动态提示词、声音脚本、素材清单五章 |
| `.drama-export.json` | 托管文件指纹及过期文件清单，重复导出时保留 |

有`audio_reference_profile`的动态提示词按目标模型输出原正文；无profile时保留全模态`text`及纯视觉`wan`兼容块。后者须人工复核，不用于声音参考投喂。音频文件只列出路径，不复制到导出目录；待制作声音不分配槽位。

导出先运行完整QC，有ERROR不写文件；WARN不阻止导出，也不逐条展示，需单独运行QC查看。`--media-root`显式启用声音文件检查。导出没有`--source/--previous/--shared-assets`选项，需要时先用QC检查同一输入。

重导出只更新未被手改的托管文件，拒绝覆盖非托管文件、手改内容或其他项目目录。过期文件保留并列入清单；恢复过期镜头仍检查原指纹。手改内容先合并回JSON，或换目录导出。全部文档预编码后才写入，但整个多文件导出不保证事务性，磁盘/I/O中途失败仍可能需要恢复或换目录。

## 切图

~~~powershell
python -B -X utf8 scripts/slice_grid.py storyboard.png --output output/slices/SHOT-001 --mode grid
python -B -X utf8 scripts/slice_grid.py scene_views.png --output output/slices/SCENE-GATE --mode grid --grid-kind spatial
python -B -X utf8 scripts/slice_grid.py character_t1.png --output output/slices/CHAR-WANQING --mode t1
~~~

| 模式或选项 | 输出 |
|---|---|
| `grid`（默认） | 默认3×3，`Shot_01.png`至`Shot_09.png`及清单；行列数可用`--rows/--cols`调整 |
| `--grid-kind storyboard`（默认） | 时序清单登记`first_frame/last_frame/middle_keyframes` |
| `--grid-kind spatial` | T5空间图，只登记`space_views`，不标动作首尾 |
| `t1` | 左55%三视图区、3张全身单图，右45%四张头像 |
| `--trim` | 各格边缘内缩比例，默认0.015（1.5%） |
| `--prefix` | grid文件名前缀，默认`Shot`，不能包含目录 |

工具按比例裁剪，不识别人像边界、网格线或关键帧含义。源图分区偏离模板时须调整；裁切不会增加像素清晰度。T5是空间参考，T6B是结构参考，首尾帧还须匹配目标风格、实际起终态及模型能力。

标准库支持非隔行8/16位灰度、RGB、RGBA等PNG，保留像素及支持的透明/常见色彩属性；索引、隔行PNG及JPEG/WebP等依赖Pillow，动画PNG先提取静帧，不保证保留全部附加元数据。

全部图块编码及目标检查完成后才写入；不覆盖源图、已有切片或清单，重切使用新目录。失败会清理本次创建的文件。

## 测试与退出码

~~~powershell
python -B -X utf8 -m unittest discover -s tests -v
~~~

四个CLI均以`0`表示成功或无ERROR、`1`表示检查/执行失败、`2`表示参数错误。仅WARN仍返回0；QC空目录或全部跳过返回1，不能据此判定制作已通过。
