# -*- coding: utf-8 -*-
"""分析 Word 模板格式：提取页面设置和各层级段落的字体/字号/颜色/对齐/行距。

用法:
    python3 analyze_template.py <模板.docx> [输出目录]

输出:
    <输出目录>/template_report.md    人类可读报告（供 Claude 判断各层级角色）
    <输出目录>/sectpr.json           页面设置

之后由 Claude 根据报告把各层级映射成 format_profile.json（供 docgen.py 使用）。
"""
import sys, os, json, re, zipfile
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _txt(p):
    return ''.join(t.text or '' for t in p.iter(f'{W}t'))


def _first_rpr(p):
    """段落中第一个 run 的属性 + 段落标记属性"""
    for r in p.iter(f'{W}r'):
        rpr = r.find(f'{W}rPr')
        if rpr is not None:
            return rpr
    ppr = p.find(f'{W}pPr')
    if ppr is not None:
        return ppr.find(f'{W}rPr')
    return None


def rpr_info(rpr):
    if rpr is None:
        return {}
    info = {}
    fonts = rpr.find(f'{W}rFonts')
    if fonts is not None:
        info['east'] = fonts.get(f'{W}eastAsia')
        info['ascii'] = fonts.get(f'{W}ascii')
    b = rpr.find(f'{W}b')
    info['bold'] = b is not None and b.get(f'{W}val') != '0'
    c = rpr.find(f'{W}color')
    if c is not None:
        info['color'] = c.get(f'{W}val')
    sz = rpr.find(f'{W}sz')
    if sz is not None:
        info['sz_pt'] = int(sz.get(f'{W}val')) / 2
    return info


def ppr_info(p):
    ppr = p.find(f'{W}pPr')
    info = {}
    if ppr is None:
        return info
    jc = ppr.find(f'{W}jc')
    if jc is not None:
        info['align'] = jc.get(f'{W}val')
    sp = ppr.find(f'{W}spacing')
    if sp is not None:
        info['line'] = sp.get(f'{W}line')
        info['lineRule'] = sp.get(f'{W}lineRule')
    ind = ppr.find(f'{W}ind')
    if ind is not None:
        info['indent'] = ind.get(f'{W}left')
    ol = ppr.find(f'{W}outlineLvl')
    if ol is not None:
        info['outlineLvl'] = ol.get(f'{W}val')
    return info


def main(tpl, outdir):
    os.makedirs(outdir, exist_ok=True)
    with zipfile.ZipFile(tpl) as z:
        doc = z.read('word/document.xml').decode('utf-8')
        names = z.namelist()
        media = [n for n in names if n.startswith('word/media/')]
    root = ET.fromstring(doc)
    body = root.find(f'{W}body')

    sect = body.find(f'{W}sectPr')
    sect_data = {}
    if sect is not None:
        pg = sect.find(f'{W}pgSz')
        mg = sect.find(f'{W}pgMar')
        if pg is not None:
            sect_data['page_w_twip'] = int(pg.get(f'{W}w'))
            sect_data['page_h_twip'] = int(pg.get(f'{W}h'))
        if mg is not None:
            sect_data['margins_twip'] = {k: int(mg.get(f'{W}{k}')) for k in ('top', 'right', 'bottom', 'left')}
        sect_data['has_footer'] = sect.find(f'{W}footerReference') is not None
    json.dump(sect_data, open(os.path.join(outdir, 'sectpr.json'), 'w'), ensure_ascii=False, indent=1)

    # 逐段落分析（有文字的）
    rows = []
    seen = set()
    for p in body.iter(f'{W}p'):
        t = _txt(p).strip()
        if not t:
            continue
        rpr = rpr_info(_first_rpr(p))
        ppr = ppr_info(p)
        # 只保留前80个不重复样式组合的段落
        key = (t[:12], json.dumps(rpr, sort_keys=True), json.dumps(ppr, sort_keys=True))
        if len(rows) >= 80:
            break
        rows.append({'text': t[:50], **rpr, **ppr})

    lines = ['# 模板格式报告', '', f'文件: {tpl}', '',
             f'页面: {sect_data.get("page_w_twip", "?")}×{sect_data.get("page_h_twip", "?")} twip '
             f'(A4=11906×16838), 边距: {sect_data.get("margins_twip")}, 页脚: {sect_data.get("has_footer")}',
             f'内嵌图片: {len(media)} 张', '',
             '| 层级线索(文本) | 字体 | 字号pt | 加粗 | 颜色 | 对齐 | 行距 | 大纲 |',
             '|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['text']} | {r.get('east','')} {r.get('ascii','')} | {r.get('sz_pt','')} | "
                     f"{'B' if r.get('bold') else ''} | #{r.get('color','')} | {r.get('align','')} | "
                     f"{r.get('line','')}{r.get('lineRule','')} | {r.get('outlineLvl','')} |")
    report = '\n'.join(lines)
    open(os.path.join(outdir, 'template_report.md'), 'w').write(report)
    print(report[:2000])
    print(f'\n→ 完整报告: {outdir}/template_report.md')
    print('下一步: 根据报告识别 标题/节标题/栏目条/知识条目/正文 的样式角色, 写 format_profile.json')


if __name__ == '__main__':
    tpl = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else '.'
    main(tpl, outdir)
