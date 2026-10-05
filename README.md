# Handout Compose — 讲义组编

从多份 PDF 教材、讲义或题库中选材，按教学目标组织知识、例题与练习，生成可编辑 Word 讲义，并保留来源记录。

本仓库由原 **handout-builder** 整合升级。仓库地址保留以延续历史，技能名称和统一入口改为 **handout-compose**。旧版工具已包含在本技能内，无须同时安装两个组编技能。

## 工作方式

学习目标 → 素材盘点 → 选材去重 → 教学编排与课时预算 → 精细转录与裁图 → Word 生成 → 教学及内容验收。

- 按学生水平和先修关系组织内容，分别安排示范与独立练习。
- 保留跨页题、共用材料、公式、图注和选项；数字以原 PDF 页面为依据。
- 记录每个输出单元的来源，并区分摘录、重述、改编和新编。
- 支持指定 Word 模板；没有模板时使用朴素讲义版。
- 将来源台账和技术记录与学生正文分开，换题时同步检查目标、编号及答案。

## 安装

```bash
git clone https://github.com/kulakeepor/claude-skill-handout-builder.git handout-compose
```

把仓库中的 `SKILL.md`、`agents/`、`references/`、`scripts/` 复制到使用工具的技能目录：

- Codex：`~/.codex/skills/handout-compose/`
- Claude Code：`~/.claude/skills/handout-compose/`

若已经安装旧版 handout-builder，先备份旧版，再将旧入口移出技能发现目录；保留一个组编入口即可。如果已有自动化脚本引用旧目录，先更新引用或保留兼容脚本路径。

辅助脚本依赖 `python-docx`、`PyMuPDF` 和 `Pillow`，建议安装到独立 Python 环境。版式检查需要可用的文档渲染工具，例如 LibreOffice；优先复用已有环境。扫描页另需实际可用的 OCR 工具，仓库不自带 OCR 引擎。

## 使用

直接说：

> 用讲义组编技能，从这些 PDF 中制作一份九年级、90 分钟的电功率复习讲义，按这个 Word 模板排版。

Codex 也可显式使用 `$handout-compose`，Claude Code 可使用 `/handout-compose`。可指定教学目标、必用内容、排除范围、课时、模板及答案版需求。

跨文档选材和重新编排使用本技能；单纯保留整份 PDF 原内容的格式转换，可使用独立的 pdf-handout-copy 技能。

## 工具与协议

| 文件 | 用途 |
|---|---|
| `scripts/pdf_extract.py` | 题目标记索引、页面和区域裁剪、图注与栏位辅助判断 |
| `scripts/glyph_ascii.py` | 疑难字形高清点阵 |
| `scripts/analyze_template.py` | Word 模板格式分析 |
| `scripts/docgen.py` | 以模板为基底生成正文和内联图片 |
| `scripts/test_pdf_extract_crop.py` | 裁剪算法回归测试 |
| `references/selection.md` | 教学设计、去重、课时取舍 |
| `references/production.md` | 制作步骤、工具接口与真实限制 |
| `references/provenance.md` | 来源、改编记录与版本对应 |
| `references/content-contract.md` | 文字、公式与图片核对 |
| `references/copy-contract.md` | 可编辑结构与复制排版 |
| `references/acceptance.md` | 内容、输出、版式及实际粘贴验收 |
| `references/workspace-template.md` | 工作记录模板 |

## 限制与验证

本技能是工作流和辅助工具，不是全自动的教学质量或 OCR 准确性保证。题目标记索引不能覆盖所有正文，裁图几何规则不能代替原页核对。`docgen.py` 的内置样式是旧学而思配置，加载模板不会自动复刻直接格式；须显式配置并检查页面设置。复杂公式和表格需要原生结构补充。

已执行：技能结构校验、22 项裁图算法回归、Word 生成与回读检查。整合后的真实多 PDF 端到端试编、全页渲染与剪贴板验证尚未完成。某次讲义的质量必须以该次任务的实际证据和验收记录为准。

运行现有裁图回归：

```bash
python3 scripts/test_pdf_extract_crop.py
```

仓库不包含教材 PDF、私人 Word 模板或生成的学生讲义。许可证沿用 MIT。
