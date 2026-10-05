# 工作记录模板

在当前项目或指定位置建立持久工作目录，不仅存临时目录。可用 Markdown、JSON 或已有结构化数据；不强制小任务搭数据库。

最小记录：`brief.md`（目标与蓝图）、`sources.md`（来源与查看范围）、`materials.json`（候选和入选单元）、`provenance.md`（输出台账）、`acceptance.md`（验收）。高清页图和配图按需保存，已有等价记录时复用。

## brief.md

```markdown
主题 / 学生水平 / 用途：
目标与达标表现 / 先修知识：
时长或估计依据：
必用 / 排除内容：
模板 / 格式 / 学生版或答案版：
已采用假设与未解决问题：

| 模块 | 学习结果 | 单元 ID 与用途 | 时间估计 | 独立检查 |
|---|---|---|---|---|

目标缺口、重复取舍、可选拓展：
```

## sources.md

```markdown
| 源 ID | 绝对路径 | SHA-256 | 总页数 | 已查看页段 | 未查看范围 |
|---|---|---|---|---|---|
```

## 单元记录示例

这是数据结构示例，不是真实题目或已完成验证；页码为 PDF 物理页码。

```json
{
  "id": "S01-U003",
  "type": "problem",
  "source_id": "S01",
  "regions": [
    {"page": 4, "bbox": [50, 420, 540, 790]},
    {"page": 5, "bbox": [50, 40, 540, 190]}
  ],
  "coordinate_system": "unrotated page points, top-left origin",
  "dependencies": [],
  "goals": ["G02"],
  "role": "independent-practice",
  "selection_reason": "检查能否独立判断适用条件",
  "duplicate_group": null,
  "operation": "excerpt",
  "changes": [],
  "transcript_file": "transcripts/S01-U003.md",
  "figures": ["figures/S01-U003-a.png"],
  "status": "selected-awaiting-transcription",
  "verification_evidence": [],
  "output_label": "练习2"
}
```

知识综合单元可以记录多个来源 ID 与区域。新编题没有源题位置，标为 `operation: original` 并另记知识依据，不制造 PDF 来源。

## provenance.md（可交付）

```markdown
讲义版本：
页码说明：从 1 开始的 PDF 物理页码。

| 输出单元/题号 | 单元 ID | 源文件 | 来源页段 | 内容操作 | 变更说明 |
|---|---|---|---|---|---|
```

## acceptance.md

```markdown
输出文件 / 版本：
| 检查项 | 结果 | 证据位置或未验证原因 |
|---|---|---|
| 核心目标与独立检查对应 | | |
| 先修顺序与课堂时间 | | |
| 必用材料与来源台账完整 | | |
| 入选内容与源页逐项核对 | | |
| 数字公式、跨页、图题与图注 | | |
| 输出回读、编号与答案对应 | | |
| 各页渲染与版式 | | |
| 目标应用复制粘贴 | | |

内容冲突、图像保真回退和交付限制：
当前入选集合与下次继续的工作：
```
