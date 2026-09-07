# -*- coding: utf-8 -*-
"""pdf_extract 裁剪收紧：几何归属 + 墨迹收边（不依赖 PDF 文件）。"""
import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from pdf_extract import (
    caption_rects_near,
    captions_outside_clip,
    column_containing,
    detect_columns,
    drop_detached_edge_bands,
    drop_small_corner_components,
    expand_bbox_with_captions,
    ink_bbox,
    is_fig_caption,
    needs_vision_refine,
    pad4,
    postprocess_crop,
    select_figs,
    y_overlap_frac,
)


class DetectColumnsTest(unittest.TestCase):
    def test_single_column_when_words_only_on_left(self):
        xs = [40 + i * 3 for i in range(30)]
        self.assertEqual(detect_columns(xs, 595), [(0.0, 595.0)])

    def test_two_columns_when_both_halves_populated(self):
        left = [50 + i for i in range(20)]
        right = [360 + i for i in range(20)]
        cols = detect_columns(left + right, 595)
        self.assertEqual(len(cols), 2)
        self.assertLess(cols[0][1], cols[1][0])

    def test_left_text_right_figure_is_single_column(self):
        """正文左右都有词，但例题标记全在左侧 → 左文右图，不当双栏。"""
        left = [50 + i for i in range(20)]
        right = [360 + i for i in range(20)]
        cols = detect_columns(left + right, 595, marker_xs=[80, 82, 85])
        self.assertEqual(cols, [(0.0, 595.0)])

    def test_true_two_column_when_markers_on_both_sides(self):
        left = [50 + i for i in range(20)]
        right = [360 + i for i in range(20)]
        cols = detect_columns(left + right, 595, marker_xs=[80, 400])
        self.assertEqual(len(cols), 2)

    def test_column_containing_picks_nearest(self):
        cols = [(0.0, 287.5), (307.5, 595.0)]
        self.assertEqual(column_containing(80, cols), cols[0])
        self.assertEqual(column_containing(400, cols), cols[1])


class SelectFigsTest(unittest.TestCase):
    def test_skips_figure_in_other_column(self):
        figs = [
            [40, 120, 200, 250],
            [320, 120, 480, 250],
        ]
        chosen, excluded = select_figs(
            figs, 100, 300, col=(0.0, 295.0), page_width=595)
        self.assertEqual(chosen, [[40, 120, 200, 250]])
        self.assertTrue(any(reason == 'other_column' for reason, _ in excluded))

    def test_keeps_full_width_figure_despite_column(self):
        figs = [[40, 120, 540, 260]]
        chosen, excluded = select_figs(
            figs, 100, 300, col=(0.0, 295.0), page_width=595)
        self.assertEqual(chosen, figs)
        self.assertEqual(excluded, [])

    def test_requires_half_vertical_overlap(self):
        figs = [[40, 280, 200, 420]]  # 20pt in region / 140pt tall
        chosen, excluded = select_figs(figs, 100, 300, page_width=595)
        self.assertEqual(chosen, [])
        self.assertTrue(any(reason == 'low_overlap' for reason, _ in excluded))

    def test_center_past_next_marker_belongs_to_next(self):
        figs = [[40, 200, 200, 360]]  # center 280, next starts 270
        self.assertGreaterEqual(y_overlap_frac(figs[0], 100, 300), 0.5)
        chosen, excluded = select_figs(
            figs, 100, 300, next_y0=270, page_h=800, page_width=595)
        self.assertEqual(chosen, [])
        self.assertTrue(any(reason == 'belongs_next' for reason, _ in excluded))

    def test_keeps_in_region_same_column(self):
        figs = [[40, 140, 200, 240]]
        chosen, excluded = select_figs(
            figs, 100, 300, col=(0.0, 295.0), page_width=595, next_y0=300)
        self.assertEqual(chosen, figs)
        self.assertEqual(excluded, [])

    def test_left_text_right_fig_kept_on_full_page_column(self):
        figs = [[320, 140, 500, 240]]
        chosen, excluded = select_figs(
            figs, 100, 300, col=(0.0, 595.0), page_width=595, next_y0=300)
        self.assertEqual(chosen, figs)
        self.assertEqual(excluded, [])


class VisionRefineHeuristicTest(unittest.TestCase):
    def test_flags_uncertain_end_and_extreme_aspect(self):
        self.assertTrue(needs_vision_refine(100, 80, 595, 842, uncertain_end=True))
        self.assertTrue(needs_vision_refine(500, 80, 595, 842))
        self.assertFalse(needs_vision_refine(180, 140, 595, 842))

    def test_flags_missing_captions(self):
        self.assertTrue(needs_vision_refine(180, 140, 595, 842, missing_captions=True))


class CaptionExpandTest(unittest.TestCase):
    def test_is_fig_caption(self):
        self.assertTrue(is_fig_caption('甲'))
        self.assertTrue(is_fig_caption('图乙'))
        self.assertTrue(is_fig_caption('图 丙'))
        self.assertFalse(is_fig_caption('例题1'))
        self.assertFalse(is_fig_caption('a'))

    def test_caption_below_bitmap_is_unioned(self):
        bbox = [100, 100, 400, 200]
        words = [(180, 208, 200, 222, '甲'), (290, 208, 310, 222, '乙')]
        caps = caption_rects_near(words, bbox)
        self.assertEqual(len(caps), 2)
        expanded = expand_bbox_with_captions(bbox, caps)
        self.assertGreaterEqual(expanded[3], 222)

    def test_captions_outside_clip(self):
        caps = [[180, 208, 200, 222]]
        self.assertTrue(captions_outside_clip(caps, [100, 100, 400, 200]))
        self.assertFalse(captions_outside_clip(caps, [100, 100, 400, 230]))

    def test_pad4(self):
        self.assertEqual(pad4(5), (5.0, 5.0, 5.0, 5.0))
        self.assertEqual(pad4((8, 4)), (8.0, 4.0, 8.0, 4.0))
        self.assertEqual(pad4((8, 4, 8, 16)), (8.0, 4.0, 8.0, 16.0))


class InkTrimTest(unittest.TestCase):
    def _canvas(self, w=200, h=200):
        img = Image.new('RGB', (w, h), (255, 255, 255))
        return img, ImageDraw.Draw(img)

    def test_ink_bbox_shrinks_to_drawing(self):
        img, d = self._canvas()
        d.rectangle([50, 60, 120, 150], fill=(0, 0, 0))
        box = ink_bbox(img, pad_px=4)
        self.assertEqual(box, (46, 56, 125, 155))

    def test_drops_stem_line_separated_by_gap(self):
        img, d = self._canvas()
        d.rectangle([20, 4, 180, 18], fill=(0, 0, 0))    # 题干残行
        d.rectangle([40, 70, 160, 180], fill=(20, 20, 20))  # 图
        out = drop_detached_edge_bands(img, min_gap=10, max_band_h_px=30)
        self.assertLess(out.size[1], 140)
        self.assertGreater(out.size[1], 90)

    def test_keeps_label_close_to_figure(self):
        img, d = self._canvas()
        d.rectangle([40, 40, 160, 150], fill=(20, 20, 20))
        d.rectangle([70, 156, 110, 168], fill=(0, 0, 0))  # 图甲，间隙 6px
        out = drop_detached_edge_bands(img, min_gap=12, max_band_h_px=30)
        box = ink_bbox(out, pad_px=0)
        self.assertGreaterEqual(out.size[1], 120)
        self.assertGreaterEqual(box[3] - box[1], 110)

    def test_drops_top_left_question_number(self):
        img, d = self._canvas()
        d.rectangle([8, 8, 28, 28], fill=(0, 0, 0))
        d.rectangle([50, 50, 170, 170], fill=(30, 30, 30))
        out = drop_small_corner_components(img)
        pix = out.load()
        self.assertGreater(sum(pix[15, 15]) / 3, 240)
        self.assertLess(sum(pix[80, 80]) / 3, 40)

    def test_fig_only_postprocess_on_file(self):
        img, d = self._canvas(220, 220)
        d.rectangle([15, 6, 200, 20], fill=(0, 0, 0))
        d.rectangle([40, 80, 180, 190], fill=(10, 10, 10))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'crop.png')
            img.save(path)
            postprocess_crop(path, mode='fig_only', pad_px=2)
            with Image.open(path) as out:
                self.assertLess(out.size[1], 160)
                self.assertGreater(out.size[1], 90)


if __name__ == '__main__':
    unittest.main()
