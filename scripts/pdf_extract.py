# -*- coding: utf-8 -*-
"""讲义 PDF 题目素材提取：图块检测、题目区域定位、条带渲染、图片裁剪。

核心认知（2026-09 实测，学而思讲义类 PDF 通用）:
- 文本层可用但缺字符：数字/物理符号（S、A₁、30Ω）被渲染成矢量路径，不出现在 get_text()
- 电路图 = 内嵌位图，bbox 宽高 45~500pt
- 缺失字形 = 矢量 drawing，宽高 <30pt 的小矩形，聚在文本行内
- 因此：结构看文本层，数值看行条带（glyph band 高清窄条），图看 bbox 裁剪
- 多裁主因：题目区间过大、把「左文右图」误判成双栏、PDF 图 bbox 带留白/题干。
  默认 300dpi clip + 只收白边（保留甲乙丙图注）；fig_only 会删底注，仅在确认没有图注时才用。
  图注仍缺时再整页渲染，用视觉千分比框补一刀。整题卡片用 question_card。

用法（通常由 SKILL.md 工作流分步调用）:
    from pdf_extract import Extractor
    ex = Extractor('素材目录')
    ex.print_index()
    figs = ex.problem_figs('f01', 3, '例题4')
    ex.crop_fig('f01', 3, bbox, 'out.png')                 # 只要图（300dpi，只收白边）
    ex.crop_question_card('f01', 3, '例题4', 'card.png')   # 原题整块（本栏）
    ex.crop_permille('f01', 3, (60,240,880,420), 't.png') # 视觉复核后的千分比框
    ex.crop_rect('f01', 3, (60,55,480,258), 'opt.png', pad=0)
    bands = ex.glyph_bands('f01', 3, y0, y1)
    ex.crop_band('f01', 3, band, 'strip.png')
"""
import os, re, glob, json

try:
    import fitz
except ImportError:  # 纯几何/收边测试可不装 PyMuPDF
    fitz = None

FIG_MIN, FIG_MAX_W = 45, 500   # 电路图 bbox 判定阈值 (pt)
GLYPH_MAX = 30                  # 矢量字形最大边 (pt)
OVERLAP_MIN = 0.5               # 图与题目区间的最小垂直重叠比例
CENTER_SLACK = 4                # 图中心允许超出区间的 pt
FULL_WIDTH_RATIO = 0.6          # 超过页宽此比例视为通栏图
CROSS_PAGE_TOP = 180            # 无下页标记时，只收页顶这么高的续图
CAPTION_RE = re.compile(r'^(?:图\s*)?[甲乙丙丁]$')
# crop_fig 默认垫边：底边加大，收「甲乙丙」；顶边收小，少带题干
FIG_PAD = (8, 4, 8, 16)         # left, top, right, bottom (pt)


# ---------- 几何（可单测）----------

def y_overlap_frac(bbox, y0, y1):
    fy0, fy1 = bbox[1], bbox[3]
    ov = max(0.0, min(fy1, y1) - max(fy0, y0))
    h = max(fy1 - fy0, 1e-6)
    return ov / h


def detect_columns(xs, page_width, min_each=8, gutter=10, mid_slack=20,
                   marker_xs=None):
    """根据词中心 x 判断单栏/双栏。双栏时返回左右两段，含中缝。

    学而思常见「左文右图」：正文词会落在左右两半，但例题/练习标记都在左侧。
    只有左右两侧都有题目标记时才当成报纸双栏，否则整页单栏。
    """
    page_width = float(page_width or 0)
    if not xs or page_width <= 0:
        return [(0.0, page_width)]
    mid = page_width / 2.0
    if marker_xs:
        left_m = [x for x in marker_xs if x < mid - mid_slack]
        right_m = [x for x in marker_xs if x > mid + mid_slack]
        if not (left_m and right_m):
            return [(0.0, page_width)]
    left = [x for x in xs if x < mid - mid_slack]
    right = [x for x in xs if x > mid + mid_slack]
    if len(left) >= min_each and len(right) >= min_each:
        return [(0.0, mid - gutter), (mid + gutter, page_width)]
    return [(0.0, page_width)]


def column_containing(x, columns):
    if not columns:
        return None
    if x is None:
        return columns[0]
    for col in columns:
        if col[0] <= x <= col[1]:
            return col
    return min(columns, key=lambda c: abs((c[0] + c[1]) / 2 - x))


def in_column(bbox, col, page_width, full_width_ratio=FULL_WIDTH_RATIO):
    if col is None:
        return True
    w = bbox[2] - bbox[0]
    if w >= page_width * full_width_ratio:
        return True
    cx = (bbox[0] + bbox[2]) / 2
    return col[0] <= cx <= col[1]


def select_figs(figs, y0, y1, col=None, page_width=595, next_y0=None, page_h=842):
    """选出属于区间 [y0, y1]、且在本栏的图。邻栏 / 重叠不足 / 中心已过下一题 的排除。"""
    chosen, excluded = [], []
    ph = page_h if page_h is not None else y1
    for b in figs:
        if not in_column(b, col, page_width):
            excluded.append(('other_column', b))
            continue
        frac = y_overlap_frac(b, y0, y1)
        if frac < OVERLAP_MIN:
            excluded.append(('low_overlap', b))
            continue
        cy = (b[1] + b[3]) / 2
        if not (y0 - CENTER_SLACK <= cy <= y1 + CENTER_SLACK):
            excluded.append(('center_outside', b))
            continue
        if next_y0 is not None and cy >= next_y0:
            excluded.append(('belongs_next', b))
            continue
        if next_y0 is not None:
            frac_next = y_overlap_frac(b, next_y0, ph)
            if frac_next > frac:
                excluded.append(('belongs_next', b))
                continue
        chosen.append(b)
    return chosen, excluded


def needs_vision_refine(clip_w, clip_h, page_w, page_h, uncertain_end=False,
                        max_aspect=4.0, max_area=0.30, missing_captions=False):
    """区间末端不确定、细长、面积过大、或甲乙丙图注落在框外 → 整页渲染后用视觉框重裁。"""
    if uncertain_end or missing_captions:
        return True
    if clip_w <= 0 or clip_h <= 0 or page_w <= 0 or page_h <= 0:
        return True
    aspect = max(clip_w / clip_h, clip_h / clip_w)
    area = (clip_w * clip_h) / (page_w * page_h)
    return aspect > max_aspect or area > max_area


def pad4(pad):
    """pad → (left, top, right, bottom)。标量四边相同；(x,y) 为左右/上下。"""
    if isinstance(pad, (int, float)):
        p = float(pad)
        return (p, p, p, p)
    if len(pad) == 2:
        x, y = float(pad[0]), float(pad[1])
        return (x, y, x, y)
    return (float(pad[0]), float(pad[1]), float(pad[2]), float(pad[3]))


def is_fig_caption(text):
    return bool(CAPTION_RE.match((text or '').strip()))


def union_rect(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def caption_rects_near(words, bbox, below=40, side=30, above=8):
    """words: (x0,y0,x1,y1,text,...)。返回紧贴图块的甲乙丙类图注框。"""
    x0, y0, x1, y1 = bbox
    found = []
    for w in words:
        text = w[4] if len(w) > 4 else ''
        if not is_fig_caption(text):
            continue
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if x0 - side <= cx <= x1 + side and y1 - above <= cy <= y1 + below:
            found.append([w[0], w[1], w[2], w[3]])
    return found


def expand_bbox_with_captions(bbox, captions):
    out = list(bbox)
    for c in captions:
        out = union_rect(out, c)
    return out


def captions_outside_clip(captions, clip, slack=2):
    """图注中心落在 clip 外（缺甲乙丙）→ True。"""
    cx0, cy0, cx1, cy1 = clip
    missed = []
    for c in captions:
        mx, my = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        if not (cx0 - slack <= mx <= cx1 + slack and cy0 - slack <= my <= cy1 + slack):
            missed.append(c)
    return missed


# ---------- 图像收边（可单测）----------

def _binary_rows(img, threshold=250, min_ink=3):
    g = img.convert('L')
    w, h = g.size
    pix = g.load()
    flags = []
    for y in range(h):
        n = 0
        ink = False
        for x in range(w):
            if pix[x, y] < threshold:
                n += 1
                if n >= min_ink:
                    ink = True
                    break
        flags.append(ink)
    return flags


def _runs(flags):
    runs, i, n = [], 0, len(flags)
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i + 1
        while j < n and flags[j]:
            j += 1
        runs.append((i, j))
        i = j
    return runs


def ink_bbox(img, threshold=250, pad_px=6):
    mask = img.convert('L').point(lambda p: 0 if p >= threshold else 255)
    box = mask.getbbox()
    if box is None:
        return None
    x0, y0, x1, y1 = box
    w, h = img.size
    return (max(0, x0 - pad_px), max(0, y0 - pad_px),
            min(w, x1 + pad_px), min(h, y1 + pad_px))


def drop_detached_edge_bands(img, threshold=250, min_gap=12, max_band_h_px=80,
                             max_band_h_ratio=0.22):
    """丢掉与主图之间有明显白缝的顶/底短带（题干残行），贴近主图的「图甲」保留。"""
    w, h = img.size
    runs = _runs(_binary_rows(img, threshold))
    if len(runs) <= 1:
        return img
    main = max(runs, key=lambda r: r[1] - r[0])
    cap = min(max_band_h_px, max(1, int(h * max_band_h_ratio)))
    keep = []
    for i, (a, b) in enumerate(runs):
        if (a, b) == main:
            keep.append((a, b))
            continue
        bh = b - a
        gap = a - main[1] if a >= main[1] else main[0] - b
        is_edge = i == 0 or i == len(runs) - 1
        if is_edge and bh <= cap and gap >= min_gap:
            continue
        keep.append((a, b))
    if not keep:
        keep = [main]
    y0 = min(a for a, _ in keep)
    y1 = max(b for _, b in keep)
    return img.crop((0, y0, w, y1))


def drop_small_corner_components(img, threshold=250, corner_frac=0.18, area_ratio=0.04):
    """涂白完全落在左上/右上角的小墨块（残留题号）。"""
    from PIL import ImageDraw
    w, h = img.size
    g = img.convert('L')
    scale = max(1, max(w, h) // 160)
    sw, sh = max(1, w // scale), max(1, h // scale)
    small = g.resize((sw, sh), resample=0)  # NEAREST
    pix = small.load()
    visited = [[False] * sw for _ in range(sh)]
    comps = []
    for y in range(sh):
        for x in range(sw):
            if visited[y][x] or pix[x, y] >= threshold:
                continue
            stack = [(x, y)]
            visited[y][x] = True
            minx = miny = 10 ** 9
            maxx = maxy = 0
            area = 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                if cx < minx:
                    minx = cx
                if cy < miny:
                    miny = cy
                if cx > maxx:
                    maxx = cx
                if cy > maxy:
                    maxy = cy
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < sw and 0 <= ny < sh and not visited[ny][nx] \
                            and pix[nx, ny] < threshold:
                        visited[ny][nx] = True
                        stack.append((nx, ny))
            comps.append((area, minx, miny, maxx, maxy))
    total = sum(c[0] for c in comps) or 1
    cw, ch = sw * corner_frac, sh * corner_frac
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for area, minx, miny, maxx, maxy in comps:
        if area / total > area_ratio:
            continue
        in_tl = maxx < cw and maxy < ch
        in_tr = minx > sw - cw and maxy < ch
        if in_tl or in_tr:
            draw.rectangle(
                [minx * scale, miny * scale,
                 min((maxx + 1) * scale, w), min((maxy + 1) * scale, h)],
                fill=(255, 255, 255))
    return out


def postprocess_crop(path, mode='whitespace', pad_px=6, threshold=250):
    """mode: False/'none' 不处理；'whitespace' 只收白边；'fig_only' 再丢掉分离残行和角题号。"""
    if mode in (False, None, 'none'):
        return path
    from PIL import Image
    with Image.open(path) as src:
        img = src.convert('RGB')
    if mode == 'fig_only':
        img = drop_detached_edge_bands(img, threshold)
        img = drop_small_corner_components(img, threshold)
    box = ink_bbox(img, threshold, pad_px)
    if box:
        img = img.crop(box)
    img.save(path)
    return path


class Extractor:
    def __init__(self, src_dir, catalog_path=None):
        if fitz is None:
            raise ImportError('PyMuPDF (fitz) is required to read PDFs')
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
    def marker_rect(self, fid, pg, marker):
        page = self.docs[fid][pg - 1]
        if marker.startswith('N'):          # 编号题 "3."
            rs = [r for r in page.search_for(f"{marker[1:]}.")
                  if r.width < 30 and r.y0 > 40]
            return min(rs, key=lambda r: r.y0) if rs else None
        rs = page.search_for(marker)
        return min(rs, key=lambda r: r.y0) if rs else None

    def marker_y(self, fid, pg, marker):
        r = self.marker_rect(fid, pg, marker)
        return r.y0 if r else None

    def page_columns(self, fid, pg):
        page = self.docs[fid][pg - 1]
        words = page.get_text('words')
        xs = [(w[0] + w[2]) / 2 for w in words]
        marker_xs = [(w[0] + w[2]) / 2 for w in words
                     if re.match(r'^(例题|练习|作业)\d+$', w[4])]
        return detect_columns(xs, page.rect.width, marker_xs=marker_xs)

    def next_marker_y(self, fid, pg, after_y, numbered=False, col=None):
        page = self.docs[fid][pg - 1]
        pat = re.compile(r'^\d+\.$') if numbered else re.compile(r'^(例题|练习|作业)\d+$')
        ys = []
        for w in page.get_text('words'):
            if not (pat.match(w[4]) and w[1] > after_y + 5):
                continue
            cx = (w[0] + w[2]) / 2
            if col is not None and not (col[0] <= cx <= col[1]):
                continue
            ys.append(w[1])
        return min(ys) if ys else None

    def problem_span(self, fid, pg, marker):
        """本题在本页的 y 区间 + 栏。找不到下一标记时 uncertain_end=True。"""
        page = self.docs[fid][pg - 1]
        rect = self.marker_rect(fid, pg, marker)
        if rect is None:
            return None
        columns = self.page_columns(fid, pg)
        col = column_containing((rect.x0 + rect.x1) / 2, columns)
        numbered = marker.startswith('N')
        y1_raw = self.next_marker_y(fid, pg, rect.y0, numbered, col=col)
        return {
            'y0': rect.y0,
            'y1': page.rect.height - 30 if y1_raw is None else y1_raw,
            'uncertain_end': y1_raw is None,
            'col': col,
            'columns': columns,
            'page_w': page.rect.width,
            'page_h': page.rect.height,
            'numbered': numbered,
        }

    def problem_figs_detailed(self, fid, pg, marker):
        """返回 (bboxes, meta)。meta.excluded 为 (reason, bbox) 列表。"""
        span = self.problem_span(fid, pg, marker)
        if span is None:
            return [], {'uncertain_end': True, 'excluded': [], 'needs_vision_refine': True}
        y0, y1, col = span['y0'], span['y1'], span['col']
        page_w, page_h = span['page_w'], span['page_h']
        next_y0 = None if span['uncertain_end'] else y1
        figs = self.catalog[fid]['pages'][pg - 1]['figs']
        chosen, excluded = select_figs(
            figs, y0, y1, col=col, page_width=page_w,
            next_y0=next_y0, page_h=page_h)

        doc = self.docs[fid]
        if y1 >= page_h - 60 and pg < len(doc):
            nxt_cols = self.page_columns(fid, pg + 1)
            try:
                col_idx = span['columns'].index(col)
            except (ValueError, IndexError):
                col_idx = 0
            ncol = nxt_cols[col_idx] if col_idx < len(nxt_cols) else column_containing(
                (col[0] + col[1]) / 2 if col else 0, nxt_cols)
            ny = self.next_marker_y(fid, pg + 1, 30, span['numbered'], col=ncol)
            nxt_page = doc[pg]
            nxt_figs = self.catalog[fid]['pages'][pg]['figs']
            if ny is not None:
                extra, ex2 = select_figs(
                    nxt_figs, 0, ny, col=ncol, page_width=nxt_page.rect.width,
                    next_y0=ny, page_h=nxt_page.rect.height)
            else:
                extra, ex2 = select_figs(
                    nxt_figs, 0, CROSS_PAGE_TOP, col=ncol,
                    page_width=nxt_page.rect.width, page_h=nxt_page.rect.height)
                span['uncertain_end'] = True
            chosen.extend(extra)
            excluded.extend(ex2)

        refine = span['uncertain_end'] or any(
            needs_vision_refine(b[2] - b[0], b[3] - b[1], page_w, page_h)
            for b in chosen)
        meta = {
            'uncertain_end': span['uncertain_end'],
            'excluded': excluded,
            'col': col,
            'y0': y0, 'y1': y1,
            'needs_vision_refine': refine,
        }
        return chosen, meta

    def problem_figs(self, fid, pg, marker):
        """题目区域内的图块 bbox（标记起到下一标记，含跨页续；栏感知、重叠收紧）"""
        chosen, meta = self.problem_figs_detailed(fid, pg, marker)
        if meta.get('uncertain_end'):
            print(f"WARN {marker} p{pg}: no next marker, region end uncertain")
        if meta.get('excluded'):
            reasons = {}
            for r, _ in meta['excluded']:
                reasons[r] = reasons.get(r, 0) + 1
            print(f"WARN {marker} p{pg}: excluded {len(meta['excluded'])} fig(s) {reasons}")
        if meta.get('needs_vision_refine'):
            print(f"WARN {marker} p{pg}: crop may need vision refine (page_png + crop_permille)")
        return chosen

    # ---------- 裁剪 ----------
    def crop_rect(self, fid, pg, rect, out, dpi=300, pad=5, trim='whitespace',
                 check_refine=True):
        page = self.docs[fid][pg - 1]
        x0, y0, x1, y1 = rect
        pl, pt, pr, pb = pad4(pad)
        clip = fitz.Rect(max(0, x0 - pl), max(0, y0 - pt),
                         min(page.rect.width, x1 + pr), min(page.rect.height, y1 + pb))
        parent = os.path.dirname(os.path.abspath(out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        page.get_pixmap(dpi=dpi, clip=clip).save(out)
        if trim:
            postprocess_crop(out, mode=trim)
        if check_refine and needs_vision_refine(
                clip.width, clip.height, page.rect.width, page.rect.height):
            print(f"WARN crop {out}: aspect/area suggests vision refine "
                  f"(page_png then crop_permille)")
        return out

    def crop_fig(self, fid, pg, bbox, out, dpi=300, pad=FIG_PAD, trim='whitespace'):
        """300dpi 按位图框裁切，只收白边。底边加大以纳入甲乙丙；仍缺则 WARN 视觉补裁。"""
        page = self.docs[fid][pg - 1]
        words = page.get_text('words')
        caps = caption_rects_near(words, bbox)
        expanded = expand_bbox_with_captions(bbox, caps)
        path = self.crop_rect(fid, pg, expanded, out, dpi=dpi, pad=pad, trim=trim,
                              check_refine=False)
        pl, pt, pr, pb = pad4(pad)
        clip = [expanded[0] - pl, expanded[1] - pt, expanded[2] + pr, expanded[3] + pb]
        # 更宽一圈再搜：文本层有图注但没进框 → 位图外矢量/更远的甲乙丙
        wider = caption_rects_near(words, bbox, below=70, side=50, above=12)
        missed = captions_outside_clip(wider, clip)
        if missed or needs_vision_refine(
                clip[2] - clip[0], clip[3] - clip[1],
                page.rect.width, page.rect.height, missing_captions=bool(missed)):
            if missed:
                print(f"WARN crop {out}: 甲乙丙图注在框外，page_png + crop_permille 补裁")
            elif needs_vision_refine(clip[2] - clip[0], clip[3] - clip[1],
                                     page.rect.width, page.rect.height):
                print(f"WARN crop {out}: aspect/area suggests vision refine "
                      f"(page_png then crop_permille)")
        return path

    def crop_problem_figs(self, fid, pg, marker, prefix):
        return [self.crop_fig(fid, pg, b, f"{prefix}_fig{i}.png")
                for i, b in enumerate(self.problem_figs(fid, pg, marker))]

    def crop_question_card(self, fid, pg, marker, out, dpi=300, pad=2, trim='whitespace'):
        """原题整块：本栏、本题标记到下一标记。保留题干，只收白边。"""
        span = self.problem_span(fid, pg, marker)
        if span is None:
            raise ValueError(f"marker {marker!r} not found on p{pg}")
        col = span['col'] or (0, span['page_w'])
        if span['uncertain_end']:
            print(f"WARN crop_question_card {marker} p{pg}: end uncertain")
        return self.crop_rect(
            fid, pg, (col[0], span['y0'], col[1], span['y1']),
            out, dpi=dpi, pad=pad, trim=trim,
            check_refine=span['uncertain_end'])

    def crop_permille(self, fid, pg, region, out, dpi=300, pad=0, trim='whitespace'):
        """视觉模型给出的千分比框 (x1,y1,x2,y2)，原点左上，范围 0–1000。只收白边，保留图注。"""
        x1, y1, x2, y2 = region
        page = self.docs[fid][pg - 1]
        W, H = page.rect.width, page.rect.height
        rect = (x1 / 1000 * W, y1 / 1000 * H, x2 / 1000 * W, y2 / 1000 * H)
        return self.crop_rect(fid, pg, rect, out, dpi=dpi, pad=pad, trim=trim,
                              check_refine=False)

    # ---------- 缺失字形行条带（数值验证用）----------
    def glyph_bands(self, fid, pg, y0, y1, merge=6):
        """返回区域内含矢量字形的行带 [(band_y0, band_y1)]，合并相邻行"""
        page = self.docs[fid][pg - 1]
        cols = self.page_columns(fid, pg)
        x0, x1 = cols[0][0] + 8, cols[-1][1] - 8
        ys = sorted(dr['rect'].y0 for dr in page.get_drawings()
                    if y0 < dr['rect'].y0 < y1 and x0 < dr['rect'].x0 < x1
                    and dr['rect'].width < GLYPH_MAX and dr['rect'].height < 20)
        bands = []
        for y in ys:
            if bands and y - bands[-1][1] < merge:
                bands[-1][1] = y + 16
            else:
                bands.append([y - 4, y + 16])
        return [tuple(b) for b in bands]

    def crop_band(self, fid, pg, band, out, dpi=300, x=None):
        if x is None:
            cols = self.page_columns(fid, pg)
            x = (cols[0][0] + 8, cols[-1][1] - 8)
        return self.crop_rect(fid, pg, (x[0], band[0], x[1], band[1]), out,
                              dpi=dpi, pad=0, trim=False, check_refine=False)

    def page_png(self, fid, pg, out, dpi=216):
        parent = os.path.dirname(os.path.abspath(out))
        if parent:
            os.makedirs(parent, exist_ok=True)
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
    parent = os.path.dirname(os.path.abspath(out))
    if parent:
        os.makedirs(parent, exist_ok=True)
    canvas.save(out)
    return out
