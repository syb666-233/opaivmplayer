# Changelog

All notable changes to LunaTrickcal / opaivmplayer localization project.

## [1.0.0 正式版] - 2026-07-06

### 公开发布（Stable）

- **发行包**：`LunaTrickcal-v1.0.0-正式版-win64.zip`
- Trickcal Revive 韩版 OCR 翻译定制版（基于 LunaTranslator GPLv3）
- 游戏内黄色译文浮层、OCR 区域排序、单次 OCR（热键 4）
- 预置 39 条 UI 韩中词典 + 12 万+ 国服文本纠错池
- **运行时自动学习**（方案 C）：静默积累 `learned_pairs.json`，无需 Frida
- 游戏专属专有名词配置（`op.exe` / OurPlay 绑定）
- 用户文档：使用说明、快速入门、FAQ、版本说明
- 一键导出学习词典脚本

### 维护者工具（源码仓库，不含于 zip）

- Frida 韩文抓取流水线（`localization_work/frida/`）
- 词典同步 `sync_dict_and_patch.bat`
- `apply_luna_trickcal.py` / `myprocess_trickcal.py`

### 已搁置（未纳入正式版）

- v1.1.0 实验：**全窗口自动韩文 OCR**（`patches/shelved/trickcal_auto_scan.py`）
  - 原因：性能与体验需进一步优化

---

## 开发记录（1.0.0 之前）

- LunaTrickcal 补丁：overlay、regions、plugin
- 优化 1/2/3/6：Frida 词典流水线、DictWithPrompt、游戏 noundict、myprocess
- overlay_translator 国服文本池构建
- OurPlay + Trickcal 游戏绑定与 savegamedata 配置
