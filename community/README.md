# 玩家配置分享

这里收录玩家整理的道路、路线收藏、拉力赛路书和完整地图配置。提交经维护者审核合并后，其他玩家可以下载 JSON 并在程序中导入。当前先提供目录和流程；尚未收录玩家投稿，不把示例或自动识别结果写成已实测配置。

## 按地图查找

| 地图 | 配置目录 |
|---|---|
| OZETI | [浏览 OZETI](ozeti/README.md) |
| BAKURANI | [浏览 BAKURANI](bakurani/README.md) |
| ZESTAFONA | [浏览 ZESTAFONA](zestafona/README.md) |

每份配置的 README 是使用入口，说明作者、版本、实测情况、文件类型及导入选项。社区配置不自动安装，也不会随合并立即写入所有玩家的程序。只增加配置通常不需要重新发布 EXE。

## 下载和导入

1. 打开对应地图下的配置包，先阅读该包的 README。
2. 打开需要的 JSON，点击 GitHub 的下载原始文件按钮；也可打开 Raw 后另存为 .json。文件内容应是 JSON，而不是网页 HTML。
3. 在程序顶部“导出配置”，备份自己当前地图的数据。
4. 按下表选择导入按钮。路网和收藏需先切换到相同地图；完整配置会自动切换到文件所属地图并替换该地图内容。

| 文件 | 由哪个按钮导出 | 如何导入 | 对当前数据的影响 |
|---|---|---|---|
| roads.json | 地图标注 → 导出路网 | 地图标注 → 导入路网 | 合并道路与路书，保留原有内容；不替换目的地、危险区和收藏 |
| routes.json | 路线收藏 → 导出收藏 | 路线收藏 → 导入收藏 | 合并完整路线与路书；导入时选择贴路及是否建立公共道路 |
| project.json | 顶部 → 导出配置 | 顶部 → 导入配置 | 替换对应地图的完整配置，包含道路、收藏、路书、危险区、目的地与规则 |

收藏导入选择“不重新贴合、不建立道路”，仍可沿原路径导航，缺少的道路只供这个收藏使用，不加入公共路网。重新贴合会依据接收者的路网计算，走法可能改变。路径导航仍受当前道路规则与危险区约束。

路网合并不强行覆盖已有道路；同 ID 但内容不同的道路可能作为新项保留，导入后应检查重复或并行路段。需要整套替换时使用完整配置，并先备份。

路网和收藏导出会附带当前地图的路书；完整配置还会携带危险区、目的地等内容。投稿前检查是否包含不想公开的信息。屏幕截取位置、HUD 和语音设备等本机设置不属于这三种共享文件。

## 目录约定

~~~text
community/
  ozeti/
    github用户名/
      配置包名/
        README.md
        roads.json       按需提供
        routes.json      按需提供
        project.json     按需提供
        preview.png      可选，已去除私人信息的预览
  bakurani/
  zestafona/
~~~

一个配置包至少包含 README.md 和一种 JSON。目录名建议使用小写英文、数字和连字符；内容名称与说明可以写中文。不同地图分开提交，不要把同名地点的坐标跨图复用。

JSON 直接来自应用导出，可以改文件名，不要为了投稿删除坐标、ID、路线分段类型、粗绘点、贴路/建路选项等字段。配置与对应说明放在一起，说明使用 [模板](SUBMISSION_TEMPLATE.md)。

当前程序只接受 schema=1；单个 JSON 不得超过 15,000,000 字节，以程序的导入限制为准。当前地图 ID 是 ozeti、bakurani、zestafona。roads.json 的 library 应为 roads，routes.json 应为 routes；project.json 使用完整配置导出。

## 不写代码也能投稿

1. 在 [项目仓库](https://github.com/greatredo/wardogs-navigator) 点击 Fork，创建到自己账号下。
2. 在自己的 Fork 中，基于最新 main 新建分支，例如 share-ozeti-supply-route。
3. 点击 Add file → Create new file，填写 community/ozeti/你的用户名/配置包名/README.md。粘贴并填写说明模板后提交，GitHub 会创建相应目录。
4. 进入刚创建的配置包目录，选择 Add file → Upload files，上传应用导出的 JSON 和可选预览，提交到同一分支。每份 JSON 已低于程序 15 MB 限制，也低于网页仓库上传的 25 MiB 限制。参见 [GitHub 文件上传说明](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)。
5. 在 Fork 中发起 Pull Request，目标仓库选择 greatredo/wardogs-navigator，目标分支 main；来源选择自己的投稿分支。
6. 说明新增或修正了什么、使用的程序版本、哪些路段实测过。需要修改时继续提交到该分支，原 PR 会更新。

一次 PR 尽量只提交一个地图上的一份配置包或一项修正。基于他人配置改进时，保留原作者和原配置链接，说明自己修改的部分。

## 审核与共享

维护者检查文件格式、地图、导入结果、道路连接、版本与作者说明，必要时请投稿者补充游戏内验证。配置语法通过不代表车辆一定能通行；未实测的道路继续保留候选状态，不用猜测标记为已确认。

静态配置不能保证当前对局没有地雷或敌方拦截。危险区应说明观察时间和适用范围，不将一次对局的信息宣传成长期安全结论。

合并后，维护者在对应地图 README 中登记配置入口，并在 [社区贡献者名单](CONTRIBUTORS.md) 中记录作者与实际贡献。任何玩家均可下载使用；遇到问题可开 Issue，并附配置路径、程序版本和复现步骤。

## 作者署名

JSON 配置、说明和代码都可以形成 Git 提交贡献，不要求贡献者必须修改程序。GitHub 自动统计与默认分支、提交邮箱关联等条件有关，Contributors 图表只显示前 100 位，不能保证每位作者立即显示。参见 [GitHub Contributors 说明](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-a-projects-contributors)。

每份配置的 README 和社区贡献者名单会独立保留署名。请维护者保留提交作者；多人协作时保留正确的 Co-authored-by 信息。代为提交需要先取得作者愿意使用的提交邮箱，优先使用其 GitHub noreply 邮箱，不猜测或要求公开私人邮箱。参见 [共同作者说明](https://docs.github.com/en/pull-requests/how-tos/commit-changes/creating-a-commit-with-multiple-authors)。

成为贡献者不自动获得合并、发布或仓库写权限。无需为了署名添加为 Collaborator。

## 许可

投稿者应有权分享提交内容。新增原创配置及说明按本项目 [Apache-2.0](../LICENSE) 提交；引用或修改其他人的资料时保留来源、署名和适用许可证。游戏地图、商标与第三方素材的权利范围见 [第三方说明](../THIRD_PARTY_NOTICES.md)。
