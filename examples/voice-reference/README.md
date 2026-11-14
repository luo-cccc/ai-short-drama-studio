# 角色声音参考准备示例

本示例在《院门线索》基础上使用Schema `1.1`登记角色晚晴的单条声音参考资产（`VOICE-WANQING`），仅供视频生成模型锁死角色音色，不额外生成整集配音音频。当前状态为`planned`（尚未生成单条参考音频，未分配音频素材槽）。

## 声音设计卡片

- **声音描述（`description`）**：青年女性，中音区，清亮偏实声；普通话，字头清楚，句尾自然收住。常态表达克制，保留自然呼吸。
- **试听文案（`audition_text`）**：今天风很轻，沿着这条路走，前面就能看见院子。你要现在出发，还是再等一会儿？

试听文案仅保存在`voices[].audition_text`中，用于生成单条角色参考样片，不进入`dialogues`或镜头台词引号。

## 校验与导出命令

在仓库根目录执行：

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/voice-reference/project.json --source examples/voice-reference/preproduction.md
python -B -X utf8 scripts/render_project.py examples/voice-reference/project.json --output output/voice-reference
python -B -X utf8 scripts/qc_check.py output/voice-reference --mode auto
~~~

当单条角色参考音频就绪后，将`status`更新为`"ready"`，补充`reference`、`audio_reference_profile`及`reference_bindings`，并使用`--media-root`校验音频文件指纹与时长。详细规则见[角色声音参考资产](../../references/voice-reference-assets.md)。
