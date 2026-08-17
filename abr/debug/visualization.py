from __future__ import annotations

from pathlib import Path

from abr.models import ImageArray, LayoutBlock, OCRLine


class DebugVisualizer:
    def draw_ocr_overlay(self, image: ImageArray, lines: list[OCRLine]) -> ImageArray:
        import cv2
        import numpy as np
        from PIL import Image, ImageDraw

        overlay = image.copy()
        image_height, image_width = overlay.shape[:2]
        for index, line in enumerate(lines, start=1):
            points = [(int(x), int(y)) for x, y in line.bbox]
            cv2.polylines(overlay, [self._as_contour(points)], isClosed=True, color=(255, 0, 255), thickness=2)

        rgb_overlay = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_overlay)
        draw = ImageDraw.Draw(pil_image)
        font = self._load_overlay_font(size=16)

        for index, line in enumerate(lines, start=1):
            points = [(int(x), int(y)) for x, y in line.bbox]
            label_text = self._overlay_label(index, line)
            anchor_x = points[0][0]
            anchor_y = max(22, points[0][1] - 12)
            box_left = max(0, min(anchor_x, image_width - 2))
            target_box_width = max(96, int(line.width * 1.35))
            target_box_width = min(target_box_width, image_width - box_left - 1)
            fitted_label_text = self._fit_label_to_width(
                draw,
                label_text,
                font,
                max_width=max(24, target_box_width - 10),
            )
            left, top, right, bottom = draw.textbbox((box_left + 4, anchor_y), fitted_label_text, font=font, anchor="ls")
            text_height = bottom - top
            box_top = max(0, anchor_y - text_height - 8)
            box_right = box_left + target_box_width
            box_bottom = min(image_height - 1, anchor_y + 5)
            draw.rectangle((box_left, box_top, box_right, box_bottom), fill=(255, 255, 255))
            draw.text(
                (box_left + 4, anchor_y),
                fitted_label_text,
                fill=(180, 25, 25),
                font=font,
                anchor="ls",
            )

        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    def draw_lines(self, image: ImageArray, lines: list[OCRLine]) -> ImageArray:
        import cv2

        overlay = image.copy()
        for index, line in enumerate(lines, start=1):
            points = [(int(x), int(y)) for x, y in line.bbox]
            color = (0, 180, 0)
            cv2.polylines(overlay, [self._as_contour(points)], isClosed=True, color=color, thickness=2)
            label = f"{index}:{line.confidence:.2f}"
            label_anchor = (points[0][0], max(20, points[0][1] - 8))
            cv2.putText(overlay, label, label_anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
        return overlay

    def draw_layout(self, image: ImageArray, blocks: list[LayoutBlock]) -> ImageArray:
        import cv2

        overlay = image.copy()
        colors = {
            "page_number": (255, 0, 0),
            "chapter_heading": (0, 0, 255),
            "paragraph": (255, 140, 0),
        }
        for block in blocks:
            points = [(int(x), int(y)) for x, y in block.bbox]
            color = colors.get(block.kind, (180, 180, 0))
            cv2.polylines(overlay, [self._as_contour(points)], isClosed=True, color=color, thickness=2)
            label_anchor = (points[0][0], max(20, points[0][1] - 8))
            cv2.putText(overlay, block.kind, label_anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        return overlay

    def draw_word_boxes(self, image: ImageArray, lines: list[OCRLine]) -> ImageArray:
        import cv2

        overlay = image.copy()
        word_index = 1
        for line in lines:
            for word in line.metadata.get("words", []):
                left = int(word["left"])
                top = int(word["top"])
                width = int(word["width"])
                height = int(word["height"])
                right = left + width
                bottom = top + height
                points = [(left, top), (right, top), (right, bottom), (left, bottom)]
                cv2.polylines(overlay, [self._as_contour(points)], isClosed=True, color=(255, 0, 255), thickness=2)
                label_anchor = (left, max(20, top - 8))
                label = f"{word_index}:{word.get('conf', 0.0):.2f}"
                cv2.putText(overlay, label, label_anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 255), 1, cv2.LINE_AA)
                word_index += 1
        return overlay

    @staticmethod
    def _as_contour(points: list[tuple[int, int]]):
        import numpy as np

        return np.array(points, dtype=np.int32).reshape((-1, 1, 2))

    @staticmethod
    def _overlay_label(index: int, line: OCRLine, max_chars: int = 96) -> str:
        text = " ".join(line.text.split())
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return f"{index}: {text}"

    @staticmethod
    def _fit_label_to_width(draw, text: str, font, max_width: int) -> str:
        if draw.textlength(text, font=font) <= max_width:
            return text

        ellipsis = "…"
        stripped = text.rstrip()
        while stripped:
            candidate = stripped.rstrip() + ellipsis
            if draw.textlength(candidate, font=font) <= max_width:
                return candidate
            stripped = stripped[:-1]
        return ellipsis

    @staticmethod
    def _load_overlay_font(size: int):
        from PIL import ImageFont

        candidates = (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        )
        for candidate in candidates:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size=size)
        return ImageFont.load_default()
