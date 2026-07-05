Trickcal + LunaTranslator 定制（LunaTrickcal）
==========================================

本目录在 localization_work 下独立开发，不修改：
  - overlay_translator/
  - luna_integration/
  - LunaTranslator_x64/（原版）

首次使用
--------
1. setup_trickcal_luna.bat
   - 复制 LunaTranslator_x64 -> runtime/
   - 应用补丁（OCR 区域排序 + 原位浮层 + 插件入口）
   - 导入 Trickcal 韩中词典

2. start_trickcal_luna.bat  启动 patched 版 Luna

补丁内容
--------
1. OCR 多区域按屏幕位置排序（上->下，左->右），修复「不按区域排列」
2. trickcal_overlay：译文浮在 OCR 区域旁，鼠标穿透，不挡游戏点击
   - 在 imageCut / ocr_run 底层记录截图坐标（兼容「单次 OCR」与持久选区）
   - 插件在 starttextsource 之前加载

性能建议（游戏卡顿时）：
   - Luna 设置里只保留 1 个翻译引擎（日志里 bing + youdaodict 各跑一遍很耗资源）
   - ocr_interval 已预设为 2.5 秒；可再调大
   - 关闭不需要的 OCR 预览窗口
3. 热键 trickcal_batch_ocr：对每个 OCR 区域分别 OCR+翻译+浮层显示
4. 热键 trickcal_delete_region：框选删除单个 OCR 译文区域（或右键点击黄色浮层删除）

Luna 内注册热键
----------------
删除单个区域：**无需手动点加号**，运行 apply_patches 后自动注册，默认按键 **6**
（可选）批量翻译：设置 -> 快捷键 -> 添加自定义 -> trickcal_batch_ocr.py

删除单个 OCR 区域
-----------------
方式一（推荐）：重启 Luna 后按 **6** 键，框选要删的区域（无需手动添加热键文件）
  - 补丁会自动写入 config.json；若无效，打开一次 设置->快捷键->自定义 即可看到
    「删除单个OCR区域」条目
方式二：在黄色译文浮层上 **右键** 删除（已修复崩溃问题）
方式三：快捷键 3 仍清除 **全部** OCR 范围与浮层

Frida 更新词典（分享给其他用户）
--------------------------------
1. frida 抓取 -> ko_captured.jsonl
2. sync_dict_and_patch.bat
   或 luna_integration/sync_from_frida.bat + apply_patches 到 runtime

导出给其他用户：
  - trickcal_noundict.json / ko_zh_pairs.json
  - 对方运行 apply_luna_trickcal.py 或本目录 sync

词典与翻译优化（已启用 1/2/3/6）
--------------------------------
详见 WORK_LOG.md 与 logs/sync_log.json

[1] Frida 抓韩文 → 词典
    scripts\run_frida_guide.bat          操作说明
    sync_dict_and_patch.bat              一键同步到 runtime
    contributions\                       放置他人分享的 json/tsv 词条

[2] DictWithPrompt（大模型 Prompt）
    已写入 runtime/userconfig/translatorsetting.json
    启用「大模型通用接口」后，长文本翻译会自动附带专有名词表

[3] 游戏专属专有名词
    绑定 Trickcal 后 sync 会自动写入 savegamedata
    未绑定时见 userconfig/trickcal_game_noundict_pending.json

[6] myprocess 译前直查 + 译后国服纠错
    runtime/userconfig/myprocess.py
    数据: runtime/data/ko_zh_pairs.json, game_strings_zh.json

浮层开关
--------
userconfig/config.json 中 trickcal_overlay_enable: true/false
