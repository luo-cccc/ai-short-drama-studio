# 角色声音参考资产

声音参考资产（`VOICE-`，Schema 1.1）只为每个发声角色（或旁白）保留**单条常态干声参考音频**供视频生成模型锁定音色身份，**不额外预生成整集逐句配音、音效或BGM音频资产**（剧中正式对白、音效与配乐由视频模型按动态提示词原生生成）。

## 1. 单条角色声音卡与样片登记

`characters[].voice`保存简短声线摘要（如“清亮女中音，匀速，句尾短收”）；需要向视频模型投喂音色参考时，在`voices`中为每个角色建立唯一一条`VOICE-`资产：

- **声音特征（`description`）**：明确年龄听感、音区、音质、语言口音、咬字与句尾习惯，并与同场角色拉开区分度。
- **试听文案（`audition_text`，可选）**：提供单人常态连续说话的5–10秒干声试听句子，不加配乐、混响或夸张哭喊。
- **单条参考音频（`reference`）**：样片定版后将`status`设为`ready`，在`reference`中直接登记目标模型`model_id`、本地相对路径`path`、64位小写SHA-256、时长`duration`及样片的实际转写`transcript`。待制作状态保留`status: "planned"`、`reference: null`。

## 2. 目标视频模型配置

在使用声音绑定的动态提示词上配置`audio_reference_profile`，声明目标模型`model_id`、`supports_voice_reference`、`max_files`、`max_file_duration`、`max_total_duration`、`formats`及依据`source`。绑定角色的`voice.reference`须满足该模型的格式与时长限制。

## 3. 动态提示词绑定规则

- 声音参考仅用于动态提示词（T7/T8/T9均可绑定），且**仅在本镜实际发声（`dialogue` / `os` / `narration`）的角色上绑定**；本镜沉默的角色不绑音频槽。
- 使用当前提示词未占用的`@素材N`槽位，在`reference_bindings`中指定`{"slot": "@素材N", "asset_id": "VOICE-*"}`，并将该`VOICE-*`列入`prompt.asset_ids`。
- **参考声明格式**：
  ```text
  @素材4 参考角色晚晴的声音身份、音色、口音与咬字。禁止继承样片台词、情绪、语速、背景声音。
  ```
- **主体行引用**：在角色行注明声音来源，例如`角色晚晴：外观参考@素材1，声音身份参考@素材4，……`；仅画外发声的角色写明`本段仅画外发声，不出现在画面，声音身份参考@素材N`。
- **样片文字隔离**：`audition_text`与`reference.transcript`仅保存在`voices`资产记录中，严禁写入`dialogues`或动态提示词的台词引号内。本镜正式台词、情绪、语速和停顿完全由镜头正文与`segments.lines`驱动。

## 4. 校验与返片核对

- 运行`qc_check.py project.json --media-root <音频根目录>`校验单条声音参考绑定归属、模型配额、文件SHA-256及WAV实测时长。
- 视频返片后核对：角色与声音是否对应、多人对话是否串声、是否误把参考样片文案串读出来、本镜情绪与口型是否自然同步。
