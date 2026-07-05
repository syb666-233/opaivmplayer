# opaivmplayer / LunaTrickcal

Trickcal Revive（韩版）在 OurPlay / 云手机上的 **韩语 OCR 实时翻译** 方案。

## 正式版下载

**GitHub Releases**（推荐）：  
https://github.com/syb666-233/opaivmplayer/releases/tag/v1.0.0-正式版

本地构建产物（维护者）：

```
localization_work/LunaTrickcal/dist/LunaTrickcal-v1.0.0-正式版-win64.zip
```

**标识**：文件名含 `正式版`，为稳定发行版（Stable）。

### 快速开始（用户）

1. 解压 zip
2. 阅读 zip 内 `快速入门.txt`
3. 双击 `start_trickcal_luna.vbs`
4. 绑定 OurPlay 游戏窗口 → 框选韩文 → 按 **4** 翻译

完整说明见 zip 内 `使用说明.txt`、`常见问题FAQ.txt`。

## 项目结构

```
localization_work/
├── LunaTrickcal/          # 定制 Luna 运行时 + 发行打包
│   ├── dist/              # 正式版 zip 输出
│   ├── docs/release/      # 用户文档模板
│   ├── patches/           # Luna 补丁源码
│   ├── scripts/           # 同步 / 打包脚本
│   └── WORK_LOG.md        # 开发工作记录
├── luna_integration/      # 词典 / myprocess 集成
├── overlay_translator/    # 国服文本池、韩中对照表
└── frida/                 # 维护者：Frida 抓词（可选）
```

## 维护者

```bat
cd localization_work\LunaTrickcal
setup_trickcal_luna.bat          REM 首次构建 runtime
sync_dict_and_patch.bat          REM 词典同步
build_release.bat                REM 打包正式版 zip
```

## 版本

| 版本 | 标识 | 说明 |
|------|------|------|
| v1.0.0 | **正式版** | 当前稳定发行版 |
| v1.1.0 | 实验（已搁置） | 全窗自动 OCR，未发布 |

详见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

本项目的 LunaTrickcal 定制部分与 LunaTranslator 相同，遵循 **GPLv3**。  
LunaTranslator 版权归 [HIllya51/LunaTranslator](https://github.com/HIllya51/LunaTranslator) 作者所有。
