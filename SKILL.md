---
name: handout-builder
description: >-
  讲义生成器：从现有教材/讲义 PDF 中选题，复刻指定 Word 模板的格式（标题、字体、颜色、排版），
  生成新的复习专题/练习讲义 docx。当用户说"生成讲义"、"做复习专题"、"按模板格式出题"、
  "从这些 PDF 挑题"、"组卷"时使用。含题目转录三重验证协议（防视觉幻觉）和电路图自动裁剪嵌入。
user-invocable: true
metadata:
  title: 讲义生成器
  version: 1.0.0
---

# 讲义生成器（PDF 选题 → 模板格式 docx）

把一批素材 PDF（教材、专题讲义）中的题目，按指定 Word 模板的格式重排成新讲义。
题目文字重排（可选中、样式统一），电路图/实验图从原 PDF 高清裁剪嵌入。

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/analyze_template.py` | 逆向模板 docx → 格式报告（字体/字号/颜色/行距/页面） |
| `scripts/docgen.py` | docx 生成器，以模板为基底保留样式表和页脚；默认=学而思培优格式，可加载 profile 定制 |
| `scripts/pdf_extract.py` | 素材 PDF 提取：题目标记索引、图块检测、区域/条带裁剪 |

依赖：`python-docx`、`PyMuPDF(fitz)`、`Pillow`、`LibreOffice(soffice, 验证用)`。

## 工作流

### Phase 1 — 解析模板格式
```bash
python3 ~/.claude/skills/handout-builder/scripts/analyze_template.py 模板.docx 工作区/
```
读 `template_report.md`，识别各层级角色（大标题/节标题/栏目条/知识条目/例题/练习）对应的样式。
若模板就是学而思系（宋体+Calibri Regular、深蓝标题、空心字栏目条），直接用 docgen 默认格式，
跳过定制；否则把识别结果写成 `format_profile.json`（键见 docgen.py DEFAULT_PROFILE）传给 DocBuilder。

### Phase 2 — 盘点素材
```python
from pdf_extract import Extractor
ex = Extractor('素材目录', '工作区/catalog.json')
ex.print_index()   # 每文件: 题目标记@y位置 | 图块bbox列表
```
建立题目索引：文件号(f01…)、题目号（例题N/练习N/编号题N）、页码。

### Phase 3 — 选题（按课堂时长）
经验值（学而思培优难度）：2小时课 ≈ 4模块 + 压轴，约 15例 + 14练 + 3压轴 ≈ 32题，正文 10-12 页。
每模块 = 知识要点（3条以内）→ 经典例题 → 巩固练习。选题优先有完整电路图的题。

### Phase 4 — 题目转录 ⚠️ 三重验证协议（必做）
素材 PDF 的数字/物理符号常是矢量路径，**不在文本层**；视觉模型整题转录幻觉率约 30%
（会把题读成"标准题"）。必须三重验证：

1. **文本层锚定**：`page.get_text()` 提取题目区域全部文字——结构和非数字文字以它为准，
   缺字符处显示为文本断裂（如"量程为 | ，"）。
2. **行条带视觉填空**：对含缺失字形的行渲染 300dpi 窄条，只读这一行：
   ```python
   bands = ex.glyph_bands(fid, pg, y0, y1)      # 定位矢量字形行带
   ex.crop_band(fid, pg, band, 'strip.png')     # → 视觉工具逐字转录该行
   ```
   视觉提示词必须中性——**不得**把推测的数据写进 prompt（会污染读图结果）。
   视觉服务并发 ≤3，串行 + 8s 间隔防限流。
3. **自洽校验**：数字要能通过物理/数学推导互证。范例：电动机题"36V 18W"、线圈2Ω、10min，
   三个干扰项 10800J(=W总)、300J(=I²Rt)、10500J(=W−Q) 全部精确可导出 → 数据组正确。
   校验不过 = 数据可疑，重裁更窄的条带重读，仍不过则弃题换题。

转录结果统一存 `transcripts.py`（dict：题干多行文本 + 图文件名 + 图宽 cm）。

### Phase 5 — 图块裁剪
```python
ex.crop_problem_figs(fid, pg, '例题4', 'figs/M2E1')   # 自动关联题目区域内的图
ex.crop_rect(fid, pg, (60,55,480,258), 'figs/OPT.png', pad=0)  # 选项块/特殊区域（含A-D标签）
hstack(['图甲.png','图乙.png'], 'figs/combo.png')     # 多图横排
```
图块判定：内嵌位图 bbox 45~500pt = 电路图；<30pt 小矢量 = 缺失字形。
设计类题的 4 个选项电路 → 裁含标签的整块区域，一张图嵌入。
表盘读数题（电流表/电压表指针）→ 嵌原图让学生自己读，不要转录指针读数。

### Phase 6 — 组装与验证
```python
from docgen import DocBuilder
b = DocBuilder('模板.docx')
b.title('XX复习专题'); b.section('一、……（建议25分钟）'); b.points_header()
b.point_item('1. 要点', ['说明', '说明'])
b.banner('经典例题'); b.subsection('小节'); b.example(['【例1】……']); b.figure('fig.png', 4.6)
b.banner('巩固练习'); b.exercise(['1. ……'])
b.banner('压轴拓展'); b.save('输出.docx')
```
验证（程序化 + 视觉各一轮）：
```bash
soffice --headless --convert-to pdf --outdir 验证目录 输出.docx
```
- 程序化：页数、每页图片数、栏目标记齐全、关键数字全文检索（注意换行会把字符串拆开，用去空白后的全文匹配）
- 视觉：抽查首/中/末 3 页（标题渲染、图清晰不越界、题目完整不被截断）
- 例题区加粗、练习区常规是模板惯例，docgen 已内置

## 关键规则（踩坑沉淀）
- 工作区放 `~/` 下，不放 `/tmp`（会被系统清理丢进度）
- PDF 文本层顺序 ≠ 视觉顺序（跨栏/跨页时文字流乱序），以 bbox 坐标判断归属
- 同一标记在不同页可能重名（如两份"练习3"），关联图块时先 `marker_y` 确认位置
- 旧版学而思学生版无答案，讲义默认学生版（无答案页）；需要答案版时另行生成
- 生成后保留工作区（脚本+素材+transcripts），改题/换题/出答案版只需改数据重跑
