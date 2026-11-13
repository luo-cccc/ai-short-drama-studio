# 角色声音参考准备示例

本例沿用《院门线索》的两镜两句台词，[交接文档](preproduction.md)登记本例项目ID、源稿和预算，并增加1.1版`VOICE-WANQING`声音设计。当前仅为`planned`：未生成音频、未试听、未指定目标视频模型，也未虚构音频文件、指纹或素材槽。原剧本两句对白保持不变。

## 声音设计交接

将声音描述与试听文案分别交给所选声音工具，按实际接口输入。下面是本例的起步设计，尚未验证听感。

声音描述：

> 青年女性，中音区，清亮偏实声；普通话，字头清楚，句尾自然收住。常态表达克制，保留自然呼吸。生成单人自然说话的干声，不加入音乐、环境声或明显混响。

试听文案：

> 今天风很轻，沿着这条路走，前面就能看见院子。你要现在出发，还是再等一会儿？

这段文案只用于制作和识别参考音频，不进入`dialogues`或镜头台词。试听选定后登记母版与转写，再根据实际视频模型裁剪或转换副本；用`audio_reference_profile`记录采用的能力与依据，用`reference_bindings.audio_reference_id`绑定副本。

## 验证与导出

在仓库根目录执行：

~~~powershell
python -B -X utf8 scripts/qc_check.py examples/voice-reference/project.json --source examples/voice-reference/preproduction.md
python -B -X utf8 scripts/render_project.py examples/voice-reference/project.json --output output/voice-reference
python -B -X utf8 scripts/qc_check.py output/voice-reference --mode auto
~~~

JSON QC会提示声音待制作；这表示计划有效，不表示已具备可投喂音频。导出项目文档列出声音卡和试听文案，逐镜文档显示未绑定状态。

登记真实音频后，使用`qc_check.py project.json --media-root 音频根目录`检查文件、指纹及可读取WAV时长，再捕获受影响依赖并导出。字段见[声音数据契约](../../references/project-data.md#角色声音参考数据)，命令见[本地工具](../../references/tools.md)，听审标准见[声音参考资产](../../references/voice-reference-assets.md)。
