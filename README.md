# 小米笔记导出（xiaomi-notes-export）

一键将小米云笔记（i.mi.com）的全部笔记导出为 **Obsidian Markdown**，包含完整正文、全部图片附件，并按文件夹归类。

本项目是 [chen1guan/xiaomi-notes-export](https://github.com/chen1guan/xiaomi-notes-export) 的改进版，修复了原脚本的若干问题（详见[与原版的差异](#与原版的差异)）。

## 太长不看（TL;DR）

1. 下载豆包
2. 把这个仓库给豆包

剩下的交给豆包：它会自动安装依赖、复用你浏览器的登录态、跑脚本，把你的小米笔记完整导出到本地。

## 功能特性

- ✅ **完整正文**：使用 `entry.content` 完整内容，并正确转换小米笔记的内部 XML 格式（标题、列表、复选框、引用、粗斜体、下划线等），兼容纯文本格式
- ✅ **全部图片附件**：下载所有图片到 `assets/`，同时处理新格式 `<img fileid>` 与旧格式 `☺ fileid` 两种正文引用
- ✅ **正确标题**：优先使用笔记真实标题（`extraInfo.title`），回退到 `subject` / 正文首行 / 创建时间
- ✅ **文件夹归类**：按 `folderId` 把笔记归入对应的文件夹子目录
- ✅ **保留登录态**：复用你本机浏览器（Edge/Chrome）的登录，无需每次手动登录

## 前置条件

- Windows 系统
- Python 3.8+
- Edge 或 Chrome 浏览器（已登录小米账号）

## 安装

```bash
pip install playwright
playwright install chromium
```

## 使用

```bash
python export.py                          # 默认导出到 D:\xiaomi，使用 Edge
python export.py --output D:\xiaomi --browser chrome
```

### 参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--output` / `-o` | 输出目录 | `D:\xiaomi` |
| `--browser` / `-b` | 浏览器（`edge` 或 `chrome`） | `edge` |

### 输出结构

```
D:\xiaomi/
├── assets/              # 全部图片附件
├── 历史/                # 按文件夹归类的笔记
│   └── 某条笔记.md
├── 绿植/
│   └── 花.md
├── 某条笔记.md          # 未归类（无文件夹）的笔记在根目录
└── _backup.json         # 全量 JSON 备份
```

每个 `.md` 文件包含 YAML frontmatter（`title` / `created` / `modified` / `source`），可直接在 Obsidian 中打开。

## 工作原理

1. 用 Playwright 复用你本机浏览器的登录态（将 profile 复制到非默认目录，以绕过 Edge/Chrome 对默认 profile 的远程调试限制）
2. 打开小米笔记页面，如需登录会在弹出的浏览器窗口中完成
3. 通过 `i.mi.com` API 分页获取全部笔记
4. 逐条获取详情（`entry.content` 完整正文 + `setting.data` 附件清单）
5. 下载全部图片附件，将正文中的图片引用替换为本地路径
6. 将笔记内部 XML 转换为 Markdown，按文件夹保存

## 与原版的差异

原仓库脚本存在三个问题，本版均已修复：

| 问题 | 原因 | 本版修复 |
|---|---|---|
| 正文不完整 | 误用了被截断的 `snippet` 预览字段，而完整内容在 `entry.content` | 改用 `entry.content` |
| 图片缺失 | 只处理了 `<img fileid>` 新格式，漏掉旧格式 `☺ fileid` 引用的大量图片 | 同时处理两种引用，下载全部附件 |
| 无文件夹 | 忽略了列表接口返回的 `folders` 信息 | 按 `folderId` 归入文件夹 |

另将标题来源修正为笔记真实标题（`extraInfo.title`）。

## 注意事项

- **浏览器登录态**：脚本会把你本机浏览器（Edge/Chrome）的 profile 复制到脚本同目录下（`edge-profile/` / `chrome-profile/`）以复用登录态。**该目录含个人登录数据，请勿提交到仓库**（已在 `.gitignore` 中排除）。如不需要，可手动删除。
- 首次运行会短暂关闭你本机的浏览器以释放 profile 锁。
- 脚本启动的浏览器窗口是可见的；若登录态失效，会提示你在窗口中重新登录。

## License

MIT
