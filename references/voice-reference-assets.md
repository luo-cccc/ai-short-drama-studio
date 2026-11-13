# 角色声音参考资产

声音参考资产（`VOICE-`，Schema 1.1）用于向支持音频参考的视频生成模型提供角色稳定音色身份。

## 1. 声音卡设计与试听

`characters[].voice`保存简短声线摘要（如“清亮女中音，匀速，句尾短收”）；需要投喂参考音频时，在`voices`中建立独立`VOICE-`资产：

- **声音特征（`description`）**：明确年龄听感、音区、音质、语言口音、咬字与句尾习惯，并与同场角色拉开区分度。
- **试听文案（`audition_text`，可选）**：提供单人常态连续说话的试听句子，与`description`分开交给语音生成或录音环节；生成干声，不加配乐、混响或夸张哭喊。
- **母版选定（`master`）**：试听通过后将`status`设为`ready`、`audition`设为`approved`，登记本地相对路径`path`、64位小写SHA-256、时长`duration`及录音的实际准确转写`transcript`。待制作状态保留`status: "planned"`、`master: null`、`references: []`。

## 2. 模型投喂副本与配置

按目标视频模型的音频限制裁剪或转换母版，登记在`voices[].references`中：
- 记录副本`id`、`model_id`、`path`、`sha256`、`duration`、母版截取区间`source_start`/`source_end`及对应`transcript`。副本不作隐式变速（`|source_end - source_start - duration| <= 0.05`）。
- 在使用声音绑定的动态提示词上配置`audio_reference_profile`，声明目标模型`model_id`、`supports_voice_reference`、`max_files`、`max_file_duration`、`max_total_duration`、`formats`及依据`source`。

## 3. 动态提示词绑定规则

- 声音参考仅用于动态提示词（T7/T8/T9均可绑定），使用当前提示词未占用的`@素材N`槽位，在`reference_bindings`中指定`asset_id`（`VOICE-*`）与`audio_reference_id`，并将该`VOICE-*`列入`prompt.asset_ids`。
- **参考声明格式**：
  ```text
  @素材4 参考角色晚晴的声音身份、音色、口音与咬字。禁止继承样片台词、情绪、语速、背景声音。
  ```
- **主体行引用**：在角色行注明声音来源，例如`角色晚晴：外观参考@素材1，声音身份参考@素材4，……`；仅画外发声的角色写明`本段仅画外发声，不出现在画面，声音身份参考@素材N`。
- **样片文字隔离**：`audition_text`与`transcript`仅保存在`voices`资产记录中，严禁写入`dialogues`或动态提示词的台词引号内。本镜正式台词、情绪、语速和停顿仍由镜头正文与`segments.lines`决定。

## 4. 校验与返片核对

- 运行`qc_check.py project.json --media-root <音频根目录>`校验声音绑定归属、模型配额、文件SHA-256及WAV实测时长。
- 视频返片后核对：角色与声音是否对应、多人对话是否串声、是否串读样片文案、本镜情绪与口型是否匹配。
