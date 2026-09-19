# 地图资源

运行所需资源随源码提供。`maps.json` 登记三张地图的尺寸、底图、定位特征、默认路网与来源文件；程序启动时只载入当前地图的定位特征。

| 地图 | 图像尺寸 | 图像与特征 | 默认路网 |
|---|---|---|---|
| OZETI | 1595 × 1451 | `ozeti.png`、`ozeti-features.npz` | `default_project.json` |
| BAKURANI | 2047 × 2048 | `maps/bakurani/map.png`、`features.npz` | `maps/bakurani/project.json` |
| ZESTAFONA | 2048 × 1779 | `maps/zestafona/map.png`、`features.npz` | `maps/zestafona/project.json` |

OZETI 的固定坐标变换保存在 `map-source.json`；另两张图的裁剪范围、比例尺和诊断样例中心保存在各自的 `source.json`。`legacy-road-seed.json` 用于识别并迁移早期默认路网，不包含用户配置。

## 来源与许可范围

公开地图配置来自 [apollyon-sys/wardogs-calculator](https://github.com/apollyon-sys/wardogs-calculator)，上游为 MIT 许可，Copyright (c) 2026 Apollyon，完整许可保留在 [wardogs-calculator-LICENSE.txt](wardogs-calculator-LICENSE.txt)。瓦片来自该项目公开的 `assets-v1` 数据集，具体地址记录在来源 JSON 中。

本项目进行了裁剪、缩放、OZETI 坐标对齐、图像特征提取、道路候选提取及部分连接修正。候选道路未经全部实测，图像和道路数据不保证对应游戏的每次更新。

0.5.3 的默认道路采用维护者于 2026-09-19 在程序内手动完善后的数据：OZETI 248 条（大路 85、小路 162、野地 1），BAKURANI 266 条（大路 103、小路 163），ZESTAFONA 206 条（大路 135、小路 69、野地 2）。本次更新道路几何、名称、分类及其备注；底图、定位特征、坐标和比例尺沿用。用户的临时行程与个人收藏不作为默认数据发布。

已有用户可通过“地图标注 → 载入内置路网”按地图更新道路；程序会先备份原配置，保留其它标注与收藏，并支持撤销。

**游戏地图图像、游戏画面和商标属于各自权利人，不在本项目 Apache-2.0 授权范围内。** 上游软件的 MIT 许可证不等于游戏原始美术素材的额外授权。本项目不声称取得游戏方对素材再分发或在线辅助功能的批准。

`sample_minimap.png` 是 OZETI 公开底图在 (505, 1245) 附近的裁剪放大图；两图的 `reference-crop.png` 也来自公开底图。它们不包含原始玩家截图、账号名或个人标注，不是游戏内缩放或实时定位效果的证明。

## 可选资源重建

以下命令从项目根目录执行，使用已安装依赖的 Python。此流程联网下载公开瓦片，在 `research/` 保存中间产物，并更新 `assets/` 中的资源；不会修改用户配置。普通启动和打包不需要运行它。

OZETI 使用已发布的坐标变换，避免改变现有道路和收藏的坐标：

```powershell
python tools/fetch_clean_map.py --map ozeti --all-styles
python tools/prepare_clean_map.py
python tools/extract_roads.py
python tools/build_map_features.py
python tools/publish_map_assets.py
python tools/make_diagnostic_sample.py
```

另外两图分别执行：

```powershell
python tools/fetch_clean_map.py --map bakurani --all-styles
python tools/prepare_extra_maps.py --map bakurani
python tools/extract_extra_roads.py --map bakurani
```

ZESTAFONA 将 `bakurani` 换为 `zestafona`。更新数据后应复核地图边界、桥梁和道路连接，运行测试及程序自检。公开裁剪样例只能验证数据处理链，游戏截图定位和实际路况仍需另外测试。
