# -*- coding: utf-8 -*-
"""讲义 PDF 题目素材提取：图块检测、题目区域定位、条带渲染、图片裁剪。

核心认知（2026-09 实测，学而思讲义类 PDF 通用）:
- 文本层可用但缺字符：数字/物理符号（S、A₁、30Ω）被渲染成矢量路径，不出现在 get_text()
- 电路图 = 内嵌位图，bbox 宽高 45~500pt
- 缺失字形 = 矢量 drawing，宽高 <30pt 的小矩形，聚在文本行内
- 因此：结构看文本层，数值看行条带（glyph band 高清窄条），图看 bbox 裁剪

用法（通常由 SKILL.md 工作流分步调用）:
    from pdf_extract import Extractor
    ex = Extractor('素材目录')            # 建 catalog: 每页图块 bbox
    ex.print_index()                      # 打印 题目标记+图块索引 → 供选题
    figs = ex.problem_figs('f01', 3, '例题4')     # 题目区域关联的图块
    ex.crop_fig('f01', 3, bbox, 'out.png')        # 裁剪电路图 (300dpi)
    ex.crop_rect('f01', 3, (60,55,480,258), 'opt.png', pad=0)  # 裁选项块区域
    bands = ex.glyph_bands('f01', 3, y0, y1)      # 含缺失字形的行带
    ex.crop_band('f01', 3, band, 'strip.png')     # 行条带 (300dpi) → 视觉精读
"""
import os, re, glob, json, fitz

FIG_MIN, FIG_MAX_W = 45, 500   # 电路图 bbox 判定阈值 (pt)
GLYPH_MAX = 30                  # 矢量字形最大边 (pt)


class Extractor:
    def __init__(self, src_dir, catalog_path=None):
        self.src = src_dir
        self.docs = {}
        self.catalog = {}
        for i, p in enumerate(sorted(glob.glob(os.path.join(src_dir, '*/*.pdf')) +
                                     glob.glob(os.path.join(src_dir, '*.pdf'))), 1):
            rel = os.path.relpath(p, src_dir)
            fid = f"f{i:02d}"
            doc = fitz.open(p)
            self.docs[fid] = doc
            self.catalog[fid] = {'rel': rel, 'pages': [
                {'page': n + 1,
                 'figs': [[round(v, 1) for v in img['bbox']]
                          for img in d.get_image_info()
                          if FIG_MIN < (img['bbox'][2] - img['bbox'][0]) < FIG_MAX_W
                          and FIG_MIN < (img['bbox'][3] - img['bbox'][1])]}
                for n, d in enumerate(doc)]}
        if catalog_path:
            json.dump(self.catalog, open(catalog_path, 'w'), ensure_ascii=False, indent=1)

    # ---------- 索引 ----------
    def print_index(self):
        """打印每个文件的题目标记位置 + 图块，供选题"""
        for fid, info in sorted(self.catalog.items()):
            print(f"## {fid} {info['rel']}")
            for p in info['pages']:
                page = self.docs[fid][p['page'] - 1]
                marks = []
                for w in page.get_text('words'):
                    if re.match(r'^(例题|练习|作业)\d+$', w[4]):
                        marks.append(f"{w[4]}@y{w[1]:.0f}")
                figs = ' '.join(f"[{i}]{tuple(round(v) for v in b)}"
                                for i, b in enumerate(p['figs']))
                if marks or figs:
                    print(f"  p{p['page']}: {' '.join(marks)} | {figs}")
            print()

    # ---------- 题目区域 ----------
    def marker_y(self, fid, pg, marker):
        page = self.docs[fid][pg - 1]
        if marker.startswith('N'):          # 编号题 "3."
            rs = [r for r in page.search_for(f"{marker[1:]}.")
                  if r.width < 30 and r.y0 > 40]
            return min(r.y0 for r in rs) if rs else None
        rs = page.search_for(marker)
        return min(r.y0 for r in rs) if rs else None

    def next_marker_y(self, fid, pg, after_y, numbered=False):
        page = self.docs[fid][pg - 1]
        pat = re.compile(r'^\d+\.$') if numbered else re.compile(r'^(例题|练习|作业)\d+$')
        ys = [w[1] for w in page.get_text('words')
              if pat.match(w[4]) and w[1] > after_y + 5]
        return min(ys) if ys else None

    def problem_figs(self, fid, pg, marker):
        """题目区域内的图块 bbox（标记起到下一标记，含跨页续）"""
        doc = self.docs[fid]
        page = doc[pg - 1]
        y0 = self.marker_y(fid, pg, marker)
        if y0 is None:
            return []
        y1 = self.next_marker_y(fid, pg, y0, marker.startswith('N')) or page.rect.height - 30
        figs = [b for b in self.catalog[fid]['pages'][pg - 1]['figs']
                if y0 - 10 <= (b[1] + b[3]) / 2 <= y1 + 10]
        if y1 >= page.rect.height - 60 and pg < len(doc):
            ny = self.next_marker_y(fid, pg + 1, 30) or page.rect.height - 30
            figs += [b for b in self.catalog[fid]['pages'][pg]['figs']
                     if (b[1] + b[3]) / 2 <= ny]
        return figs

    # ---------- 裁剪 ----------
    def crop_rect(self, fid, pg, rect, out, dpi=300, pad=5):
        page = self.docs[fid][pg - 1]
        x0, y0, x1, y1 = rect
        clip = fitz.Rect(max(0, x0 - pad), max(0, y0 - pad),
                         min(page.rect.width, x1 + pad), min(page.rect.height, y1 + pad))
        page.get_pixmap(dpi=dpi, clip=clip).save(out)
        return out

    def crop_fig(self, fid, pg, bbox, out, dpi=300, pad=5):
        return self.crop_rect(fid, pg, bbox, out, dpi, pad)

    def crop_problem_figs(self, fid, pg, marker, prefix):
        return [self.crop_fig(fid, pg, b, f"{prefix}_fig{i}.png")
                for i, b in enumerate(self.problem_figs(fid, pg, marker))]

    # ---------- 缺失字形行条带（数值验证用）----------
    def glyph_bands(self, fid, pg, y0, y1, merge=6):
        """返回区域内含矢量字形的行带 [(band_y0, band_y1)]，合并相邻行"""
        page = self.docs[fid][pg - 1]
        ys = sorted(dr['rect'].y0 for dr in page.get_drawings()
                    if y0 < dr['rect'].y0 < y1 and 35 < dr['rect'].x0 < 560
                    and dr['rect'].width < GLYPH_MAX and dr['rect'].height < 20)
        bands = []
        for y in ys:
            if bands and y - bands[-1][1] < merge:
                bands[-1][1] = y + 16
            else:
                bands.append([y - 4, y + 16])
        return [tuple(b) for b in bands]

    def crop_band(self, fid, pg, band, out, dpi=300, x=(40, 555)):
        return self.crop_rect(fid, pg, (x[0], band[0], x[1], band[1]), out, dpi, pad=0)

    def page_png(self, fid, pg, out, dpi=150):
        self.docs[fid][pg - 1].get_pixmap(dpi=dpi).save(out)
        return out


def hstack(paths, out, pad=40):
    """多图横排组合（图甲+图乙 / 双表盘 等）"""
    from PIL import Image
    imgs = [Image.open(p) for p in paths]
    h = max(im.height for im in imgs)
    w = sum(im.width for im in imgs) + pad * (len(imgs) - 1)
    canvas = Image.new('RGB', (w, h), (255, 255, 255))
    x = 0
    for im in imgs:
        canvas.paste(im, (x, (h - im.height) // 2))
        x += im.width + pad
    canvas.save(out)
    return out
