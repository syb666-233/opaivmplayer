# LunaTrickcal 优化工作记录

> 执行时间：2026-07-05（UTC+8 约 20:07）  
> 任务：推进优化 **1 / 2 / 3 / 6**（Frida 词典、DictWithPrompt、游戏专属词典、myprocess 增强）  
> 执行者：Cursor Agent（用户离线授权）

---

## 总览

| 优化 | 状态 | 说明 |
|------|------|------|
| **1** Frida → 词典流水线 | ✅ 已实现 | 脚本 + bat + 日志 + 外部贡献合并 |
| **2** DictWithPrompt | ✅ 已写入配置 | `chatgpt-3rd-party` 已启用 Trickcal Prompt |
| **3** 游戏专属专有名词 | ✅ 已实现 | 绑定游戏后自动写入；未绑定有 pending 模板 |
| **6** myprocess 增强 | ✅ 已实现 | 译前韩中直查 + 译后国服纠错 |

**一键应用命令（已在本机执行成功）：**

```bat
cd d:\ch\opaivmplayer\localization_work\LunaTrickcal
py -3 apply_trickcal_optimizations.py
```

**词典同步命令（Frida 抓词后）：**

```bat
sync_dict_and_patch.bat
```

---

## 优化 1：Frida 词典流水线

### 目标

Frida 抓韩文 → 生成韩中对照 → 导入 Luna 全局/游戏词典，支持多人贡献词条合并。

### 新增/修改文件

| 文件 | 作用 |
|------|------|
| `scripts/sync_trickcal_dict.py` | 全流程：合并贡献 → build_ko_zh_pairs → export → apply |
| `scripts/merge_external_dict.py` | 合并 `contributions/*.json|tsv` |
| `scripts/run_frida_guide.bat` | Frida 操作步骤说明 |
| `sync_dict_and_patch.bat` | 用户一键同步（更新） |
| `contributions/README.txt` | 外部词典贡献格式说明 |
| `luna_integration/sync_from_frida.bat` | 同步到 LunaTrickcal/runtime（更新） |

### 数据流

```
frida/ko_captured.jsonl
    ↓ build_ko_zh_pairs.py
overlay_translator/ko_zh_pairs.json
    ↓ (+ contributions/ 合并)
export_luna_glossary.py → trickcal_noundict.json
    ↓ apply_luna_trickcal.py
runtime/userconfig/config.json (noundictconfig_ex)
runtime/data/ko_zh_pairs.json
runtime/data/game_strings_zh.json
```

### 执行结果（2026-07-05）

- `build_ko_zh_pairs.py`：**39 条**（均为 glossary，Frida 抓取文件当前为空或无新词条）
- `export_luna_glossary.py`：导出 39 条到 `trickcal_noundict.json`
- 日志写入：`logs/sync_log.json`（每次 sync 追加，最多保留 50 条）

### 用户后续操作（Frida）

1. 运行 `scripts/run_frida_guide.bat` 查看步骤  
2. 启动 `frida/start_capture_server.bat`  
3. `adb connect` + `adb forward` + `frida -U ... hook_capture_ko.js`  
4. 游戏内浏览 UI/剧情  
5. 运行 `sync_dict_and_patch.bat`  

### 分享词典给他人 / 接收他人词典

- 导出：`luna_integration/trickcal_noundict.tsv` 或 `overlay_translator/ko_zh_pairs.json`  
- 导入：将 json/tsv 放入 `contributions/` 后运行 sync  

---

## 优化 2：DictWithPrompt

### 目标

大模型翻译时，将专有名词表注入 Prompt，改善长剧情/说明文本的译名一致性。

### 修改位置

`runtime/userconfig/translatorsetting.json` → `chatgpt-3rd-party.args`：

| 字段 | 值 |
|------|-----|
| `使用自定义promt` | `true` |
| `自定义promt` | Trickcal 韩语手游 system 说明（简中输出） |
| `use_user_user_prompt` | `true` |
| `user_user_prompt` | `{DictWithPrompt[...]}\n请翻译以下韩语：\n{sentence}` |

### 重要说明

- **仅对「大模型通用接口」生效**；当前主翻译为 Bing 时，日常 UI 仍走 Bing + noundict + myprocess  
- 需在 Luna 中**启用** `fanyi.chatgpt-3rd-party.use = true` 并配置 API Key / 模型  
- DictWithPrompt 依赖「专有名词翻译」已开启（`transoptimi.noundict = true`）✅  

### 验证方法

1. Luna → 翻译设置 → 启用「大模型通用接口」，填入 API  
2. 临时只开 LLM、关闭 Bing  
3. 框选含专有名词的长韩文（如含「캐시 상점」的句子）  
4. 查看 LLM 请求 Prompt 应含 `点券商店` 等对照行（Luna 调试/日志）  

---

## 优化 3：游戏专属专有名词

### 目标

Luna「游戏设置 → 翻译优化 → 专有名词翻译」使用 Trickcal 专用词典（与全局词典可合并）。

### 实现方式

`apply_luna_trickcal.py` → `apply_game_private_noundict()`：

- 扫描 `userconfig/savegamedata*.json`  
- 匹配 title/path 含 `trickcal` / `epidgames` / `트릭컬` 的游戏条目  
- 写入：`noundictconfig_ex`、`noundict_use=true`、`noundict_merge=true`、`transoptimi_followdefault=false`  

### 当前执行结果

- **savegamedata 中尚无 Trickcal 绑定记录** → 未匹配到 game uid  
- 已生成 **`runtime/userconfig/trickcal_game_noundict_pending.json`**（39 条待应用模板）  

### 用户后续操作

1. Luna 绑定 Trickcal / AIVM 游戏窗口（产生 savegamedata 条目）  
2. 再运行 `sync_dict_and_patch.bat`  
3. Luna → 游戏设置 → 翻译优化 → 专有名词翻译 → 应看到 Trickcal 专属词条  
4. `noundict_merge=true` 表示**同时使用**全局 + 游戏词典（Luna postusewhich 模式 3）  

---

## 优化 6：myprocess 译前直查 + 译后纠错

### 目标

- **译前**：高置信韩中对照表命中 → 跳过机翻，直接输出中文  
- **译后**：国服 12.6 万条文本池模糊匹配 → 修正机翻措辞  

### 修改文件

`luna_integration/myprocess_trickcal.py` → 复制到 `runtime/userconfig/myprocess.py`

### 逻辑摘要

```
process_before(韩文):
  查 ko_zh_pairs / trickcal_noundict
  置信度 ≥ 0.82 → context.direct_zh = 中文

process_after(译文, context):
  若 direct_zh → 直接返回
  否则 → game_strings_zh 模糊匹配（阈值 0.84/0.72/0.68）
```

### 数据文件（已同步到 runtime/data/）

| 文件 | 大小/条数 | 来源 |
|------|-----------|------|
| `ko_zh_pairs.json` | 39 条 | overlay_translator |
| `trickcal_noundict.json` | 39 条 | luna_integration |
| `game_strings_zh.json` | ~125896 条 | overlay_translator（国服 APK） |

### 自动化测试结果

```text
process_before('캐시 상점') → process_after(..., direct_zh) → '点券商店'  ✅
```

---

## 变更文件清单

### 新增

- `LunaTrickcal/apply_trickcal_optimizations.py`
- `LunaTrickcal/scripts/sync_trickcal_dict.py`
- `LunaTrickcal/scripts/merge_external_dict.py`
- `LunaTrickcal/scripts/run_frida_guide.bat`
- `LunaTrickcal/contributions/README.txt`
- `LunaTrickcal/contributions/example_contributions.json`
- `LunaTrickcal/logs/sync_log.json`（运行后生成）
- `LunaTrickcal/logs/optimization_apply.json`（运行后生成）
- `LunaTrickcal/runtime/data/*`（同步数据）
- `LunaTrickcal/runtime/userconfig/trickcal_game_noundict_pending.json`

### 修改

- `luna_integration/apply_luna_trickcal.py`（DictWithPrompt + 游戏专属 + data 同步）
- `luna_integration/myprocess_trickcal.py`（译前直查 + 路径解析）
- `luna_integration/sync_from_frida.bat`
- `LunaTrickcal/sync_dict_and_patch.bat`
- `LunaTrickcal/README.txt`

### 未修改（按约定）

- `overlay_translator/` 主程序逻辑（仅调用现有 build_ko_zh_pairs）
- `LunaTranslator_x64/` 原版
- `LunaTranslator.exe` 二进制

---

## 回归测试清单（用户回来后）

### 基础启动

- [ ] `start_trickcal_luna.vbs` 正常启动，无空白 cmd  
- [ ] OCR + 浮层仍正常（`4` 单次 OCR）  

### 优化 1（词典）

- [ ] Frida 抓词后 `ko_captured.jsonl` 有新行  
- [ ] `sync_dict_and_patch.bat` 成功，`logs/sync_log.json` 中 `"success": true`  
- [ ] `config.json` 的 `noundictconfig_ex` 条数增加  

### 优化 2（LLM Prompt）

- [ ] 启用大模型接口后，长句翻译专名更一致  
- [ ] `translatorsetting.json` 中 `使用自定义promt: true`  

### 优化 3（游戏专属）

- [ ] 绑定 Trickcal 后重跑 sync  
- [ ] 游戏设置 → 专有名词翻译 可见词条  

### 优化 6（myprocess）

- [ ] 框选「캐시 상점」→ 浮层显示「点券商店」（即使 Bing 译错也应被 direct_zh 纠正）  
- [ ] 长文本机翻后措辞更接近国服（若国服池有近似句）  

---

## 已知限制

1. **Frida 需用户本机操作**：Agent 无法在离线环境连接 AIVM adb  
2. **游戏专属词典需先绑定窗口**：当前 savegamedata 为空，pending 模板已就绪  
3. **DictWithPrompt 需用户启用 LLM 并填 API**：配置已写好，Bing 主翻译时不会触发  
4. **example_contributions.json** 以 `example_` 开头，**不会**被 merge 脚本导入（故意跳过）  

---

## 日志位置速查

| 路径 | 内容 |
|------|------|
| `LunaTrickcal/logs/sync_log.json` | 每次词典 sync 的步骤与 stdout |
| `LunaTrickcal/logs/optimization_apply.json` | apply_trickcal_optimizations 执行记录 |
| `LunaTrickcal/runtime/userconfig/trickcal_overlay.log` | 浮层/OCR 调试 |
| `localization_work/frida/ko_captured.jsonl` | Frida 原始抓取 |

---

## 修复记录

| 问题 | 处理 |
|------|------|
| `merge_external_dict.py` 路径多一层 `LunaTrickcal/` | 已修正为 `ROOT/contributions` |
| `example_*.json` 污染词典 | merge 脚本跳过 `example_` 前缀文件 |

---

## v1.0.0 正式版发行（2026-07-06）

### 决策

- **正式版基准**：首次打包 v1.0.0（手动 OCR + 运行时学习），**不含** v1.1.0 全窗自动 OCR（已移至 `patches/shelved/`）
- **发行包**：`dist/LunaTrickcal-v1.0.0-正式版-win64.zip`
- **用户文档**：`docs/release/` → 打包时写入 zip 根目录

### 打包命令

```bat
cd localization_work\LunaTrickcal
build_release.bat
```

### GitHub

- 仓库根目录：`README.md`、`CHANGELOG.md`、`.gitignore`
- 源码含 patches / scripts / luna_integration；**不含** `runtime/`（体积过大，用户用 zip）

---

*本文档随本次优化一同提交，后续 sync 可在 `logs/sync_log.json` 追加追踪。*
