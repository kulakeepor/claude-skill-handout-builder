# Handout Builder — 讲义生成器（Claude Code Skill）

**English TL;DR:** A Claude Code skill that builds review/exercise handouts (Word .docx) by selecting problems from your existing textbook/worksheet PDFs and replicating the exact formatting of any Word template — fonts, colors, heading hierarchy, layout. Circuit diagrams and experiment figures are auto-cropped from the source PDFs at 300 dpi and embedded. Ships with a "three-fold verification protocol" that catches vision-model transcription hallucinations on PDFs whose numbers are vector outlines.

---

## 它解决什么问题

老师手里往往有几十份现成的专题讲义 PDF，想组一份复习卷时面临两难：

- **直接截图拼文档** → 格式混乱，无法编辑，篇幅失控
- **手动重新录入** → 工作量巨大，电路图没法画

这个 skill 让 Claude Code 完成整个流程：

```
素材 PDF 们 + 一份 Word 模板
        │
        ├─ ① 模板格式逆向（字体/字号/颜色/行距/层级 → 格式档案）
        ├─ ② 素材盘点（题目标记索引 + 电路图自动检测）
        ├─ ③ 按课堂时长选题（如 2 小时 ≈ 4 模块 32 题）
        ├─ ④ 题目转录 ⚠️ 三重验证（防视觉幻觉）
        ├─ ⑤ 电路图 300dpi 高清裁剪（含选项电路块、表盘图）
        └─ ⑥ 组装 docx → 转 PDF 双重校验 → 交付
        │
生成：格式与模板完全一致、文字可编辑、原版电路图嵌入的讲义
```

## 安装

```bash
git clone https://github.com/kulakeepor/claude-skill-handout-builder.git
cp -r claude-skill-handout-builder ~/.claude/skills/handout-builder
```

依赖（Python 3.8+）：

```bash
pip install python-docx PyMuPDF Pillow
brew install --cask libreoffice   # 验证排版用，也可不装跳过视觉校验
```

## 使用

对 Claude Code 说（自动触发 skill）：

- “从这些 PDF 挑题，按 XX 模板格式生成一份 2 小时复习讲义”
- “做一份期中复习专题 / 组卷”

或显式调用：`/handout-builder`

首次效果实测：21 份专题 PDF（161 页）→ 11 页复习讲义，31 张电路图，格式与模板逐项一致（标题深蓝 14pt、知识要点绿色、大栏目空心字体、例题区加粗练习区常规、页脚页码）。

## 核心机制：三重验证协议（这个 skill 最重要的部分）

许多教辅 PDF 的**数字和物理符号是矢量路径**，不在文本层里。视觉模型整题转录的幻觉率实测约 30%——它会把题"读成"一道相似的标准题，数据全错但看起来很合理。协议：

1. **文本层锚定** — 题目结构、非数字文字以 `get_text()` 为准；缺字符处表现为文本断裂（如"量程为 | ，"）
2. **行条带视觉填空** — 只对含矢量字形的行渲染 300 dpi 窄条逐行精读（`glyph_bands()` + `crop_band()`）；视觉提示词必须中性，写入推测数据会污染读图
3. **自洽校验** — 数据要能通过学科推导互证。例：电动机题"36V 18W"、线圈 2Ω、10min，四个选项 10800J(=W总)、300J(=I²Rt)、10500J(=W−Q) 全部精确可导出 → 数据组锁定

校验不过 → 重裁更窄条带重读 → 仍不过则弃题换题。

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/analyze_template.py` | 逆向任意 Word 模板 → 样式报告（各层级字体/字号/颜色/对齐/行距） |
| `scripts/docgen.py` | docx 生成器：以模板为基底保留样式表/页脚，清空正文注入新内容；默认格式档案=学而思培优讲义，可用 `format_profile.json` 定制任意模板 |
| `scripts/pdf_extract.py` | 素材提取：题目标记索引、图块检测（45~500pt 位图=插图）、题目区域关联、矢量字形行带定位、区域/条带裁剪、多图横排 |

## 定制其他模板

`analyze_template.py` 产出样式报告后，把各层级角色映射成 `format_profile.json`（键见 `docgen.py` 的 `DEFAULT_PROFILE`），传给 `DocBuilder(template, 'format_profile.json')` 即可。默认档案已内置常见培优讲义样式，同款模板可直接用。

## 限制

- 素材需有文本层（纯扫描件需先 OCR）
- 题目标记需为"例题N/练习N/作业N/编号."风格（其他风格改 `pdf_extract.py` 的正则即可）
- 生成的讲义为学生版（无答案）；答案版需另行生成
- ⚠️ 请仅用于自己有权的素材：skill 不上传、不包含任何教材内容，仓库中只有代码

## License

MIT
