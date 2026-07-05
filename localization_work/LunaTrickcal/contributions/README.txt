# 外部韩中词条贡献目录

将其他用户分享的词典文件放在此目录，然后运行：

```bat
cd d:\ch\opaivmplayer\localization_work\LunaTrickcal
sync_dict_and_patch.bat
```

## 支持格式

### JSON（推荐）

文件名任意，例如 `user_a_ui.json`：

```json
{
  "entries": [
    {"ko": "캐시 상점", "zh": "点券商店", "info": "user_a"},
    {"src": "모집", "dst": "招募"}
  ]
}
```

### TSV

例如 `shared.tsv`：

```
src	dst	info
모집	招募	user_b
```

## 合并规则

- 相同韩文（忽略空白）已存在时，**新文件覆盖**旧译文
- 合并后写入 `overlay_translator/ko_zh_pairs.json`，再导出到 Luna

## 示例

见 `example_contributions.json`（可删除或替换为真实数据）
