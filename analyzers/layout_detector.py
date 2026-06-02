"""Per-page layout heuristics (tables / complexity) from a PyMuPDF page."""

from __future__ import annotations

from typing import Any


def page_layout_metrics(page: Any) -> dict:
    """Return image_area_ratio, line_count, rect_count, table_likelihood."""
    rect = page.rect
    page_area = max(float(rect.width) * float(rect.height), 1.0)

    image_area = 0.0
    try:
        for img in page.get_image_info():
            bbox = img.get("bbox")
            if bbox:
                w = abs(bbox[2] - bbox[0])
                h = abs(bbox[3] - bbox[1])
                image_area += w * h
    except Exception:  # noqa: BLE001
        pass

    h_lines = v_lines = rects = 0
    try:
        for d in page.get_drawings():
            for item in d.get("items", []):
                kind = item[0]
                if kind == "l":  # line segment
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 1.5:
                        h_lines += 1
                    elif abs(p1.x - p2.x) < 1.5:
                        v_lines += 1
                elif kind == "re":  # rectangle
                    rects += 1
    except Exception:  # noqa: BLE001
        pass

    # Grid-like ruling (many horizontal + vertical lines) suggests tables.
    table_likelihood = 0.0
    if h_lines >= 3 and v_lines >= 2:
        table_likelihood = min(1.0, (h_lines + v_lines) / 40.0)

    return {
        "image_area_ratio": round(min(image_area / page_area, 1.0), 3),
        "line_count": h_lines + v_lines,
        "rect_count": rects,
        "table_likelihood": round(table_likelihood, 3),
    }
