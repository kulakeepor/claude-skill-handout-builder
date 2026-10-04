#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""矢量字形 1200dpi 点阵渲染器 —— 数字/下标逐字裁决工具。

用法:
  # 渲染指定区域的每个矢量字形（各自独立点阵）:
  python3 glyph_ascii.py 素材.pdf -p 5 -r 338,120,384,144

  # 自动找该行文本层空槽（字形所在处）再逐字渲染:
  python3 glyph_ascii.py 素材.pdf -p 5 -a 128

  # -c 控制点阵宽度（默认 24），--paths 打印字形 bbox 列表

判形规则（衬线斜体数字，配合点阵阅读）:
  0=整椭圆  1=旗+竖+衬线  2=上环+左下斜线+宽底横  3=上环左侧中断+中部收口+下环
  4=斜线+横杠+竖尾       5=顶横杠+左竖+中横+下右环  6=左竖从中上部接管+下环
  7=顶横杠+斜线无左竖    8=左侧笔画连续贯穿上下双环  9=上环封闭+右侧尾、无下环
  字母宽度参考: V≈8.3pt  W≈11.4  Ω≈7.3  A≈8  R/P≈8.3  U≈8.4  S≈5  L≈6  "="≈7.6(双横)
  ⚠️ 下标宽度(₁≈2.8/₂≈3.2pt)会漂移，只能参考不能定案；点阵形状才是判据。
"""
import argparse
import io

import fitz
import numpy as np
from PIL import Image


def ascii_glyph(page, rect, cols=24, dpi=1200, thr=185):
    pix = page.get_pixmap(clip=fitz.Rect(*rect), dpi=dpi)
    img = np.array(Image.open(io.BytesIO(pix.tobytes('png'))).convert('L'))
    ink = img < thr
    if not ink.any():
        return None, None
    r = np.where(ink.any(1))[0]
    c = np.where(ink.any(0))[0]
    g = ink[r[0]:r[-1] + 1, c[0]:c[-1] + 1]
    h, w = g.shape
    nr = max(8, int(cols * h / w * 0.5))
    lines = []
    for i in range(nr):
        lines.append(''.join(
            '#' if g[int(i * h / nr):int((i + 1) * h / nr),
                    int(j * w / cols):int((j + 1) * w / cols)].any() else '.'
            for j in range(cols)))
    return '\n'.join(lines), g.shape


def glyph_paths(page, region):
    """区域内矢量字形 bbox 列表（按 y,x 排序）。注意：部分字形(Ω/V 等)不在 drawings 里。"""
    x0, y0, x1, y1 = region
    out = []
    for d in page.get_drawings():
        r = d['rect']
        if (r.x0 >= x0 - 1 and r.x1 <= x1 + 1 and r.y0 >= y0 - 1 and r.y1 <= y1 + 1
                and r.width > 0.3):
            out.append((round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)))
    out.sort(key=lambda t: (round(t[1]), t[0]))
    return out


def line_gap_slots(page, y_center, x_lo=52, x_hi=545, min_gap=7):
    """找 y_center 附近一行文本层的空槽（字形聚集处）。"""
    d = page.get_text('dict')
    spans = []
    for b in d['blocks']:
        if b['type'] != 0:
            continue
        for l in b['lines']:
            if abs(l['bbox'][1] - y_center) > 6:
                continue
            for s in l['spans']:
                if s['text'].strip():
                    spans.append((s['bbox'][0], s['bbox'][2]))
    if not spans:
        return []
    spans.sort()
    dedup = [list(spans[0])]
    for s in spans[1:]:
        if s[0] > dedup[-1][1] + 1:
            dedup.append(list(s))
        else:
            dedup[-1][1] = max(dedup[-1][1], s[1])
    gaps = []
    prev = x_lo
    for s in dedup:
        if s[0] - prev >= min_gap:
            gaps.append((round(prev, 1), round(s[0], 1)))
        prev = max(prev, s[1])
    if x_hi - prev >= min_gap:
        gaps.append((prev, x_hi))
    return gaps


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('pdf')
    ap.add_argument('-p', '--page', type=int, required=True, help='页码(1起)')
    ap.add_argument('-r', '--rect', help='x0,y0,x1,y1 区域(pt)')
    ap.add_argument('-a', '--auto', type=float, help='行 y 坐标(pt)，自动找该行空槽')
    ap.add_argument('-c', '--cols', type=int, default=24)
    ap.add_argument('--paths', action='store_true', help='只列字形 bbox')
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    page = doc[args.page - 1]

    regions = []
    if args.rect:
        regions.append(tuple(float(v) for v in args.rect.split(',')))
    elif args.auto:
        for g0, g1 in line_gap_slots(page, args.auto):
            regions.append((g0 - 1, args.auto - 3, g1 + 1, args.auto + 16))
    else:
        ap.error('需要 -r 或 -a')

    for reg in regions:
        print(f'===== 区域 {reg} =====')
        paths = glyph_paths(page, reg)
        if args.paths:
            for p in paths:
                print(' ', p)
            continue
        if not paths:
            print('  (无矢量字形 path——可能该处是文本层字符，或 Ω/V 类不进 drawings 的字形，改用 -r 放大整段渲染)')
            art, _ = ascii_glyph(page, reg, cols=max(args.cols, 40))
            if art:
                print(art)
            continue
        for (x0, y0, x1, y1) in paths:
            h = y1 - y0
            tag = '下标' if h < 6 else f'{h:.1f}pt'
            art, shape = ascii_glyph(page, (x0 - 0.6, y0 - 0.6, x1 + 0.6, y1 + 0.6), cols=args.cols)
            print(f'-- x{x0} w{x1 - x0:.1f} [{tag}]')
            print(art if art else '  (空)')


if __name__ == '__main__':
    main()
