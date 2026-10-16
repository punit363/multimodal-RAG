"""Extract source locations without guessing missing PDF coordinates."""

import math
from typing import Any, Dict, List, Optional


def _page_number(element: Any) -> Optional[int]:
    value = getattr(getattr(element, "metadata", None), "page_number", None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _normalized_rect(element: Any) -> Optional[Dict[str, float]]:
    coordinates = getattr(getattr(element, "metadata", None), "coordinates", None)
    if coordinates is None:
        return None
    system = getattr(coordinates, "system", None)
    if type(system).__name__ != "PixelSpace":
        return None
    width = getattr(system, "width", None)
    height = getattr(system, "height", None)
    points = getattr(coordinates, "points", None)
    if not width or not height or not points:
        return None
    try:
        xs = [float(point[0]) / float(width) for point in points]
        ys = [float(point[1]) / float(height) for point in points]
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in xs + ys):
        return None
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    if left >= right or top >= bottom:
        return None
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def source_location(chunk: Any) -> Dict[str, Any]:
    """Return real page numbers and a highlight only when every element is located."""
    metadata = getattr(chunk, "metadata", None)
    elements: List[Any] = list(getattr(metadata, "orig_elements", None) or [])
    if not elements:
        elements = [chunk]

    pages = sorted({page for element in elements if (page := _page_number(element))})
    if not pages and (page := _page_number(chunk)):
        pages = [page]

    located_elements = sum(_page_number(element) is not None for element in elements)
    page_location_status = (
        "unavailable" if not pages else "complete" if located_elements == len(elements) else "partial"
    )
    element_types = sorted({type(element).__name__ for element in elements})
    result: Dict[str, Any] = {
        "page_numbers": pages,
        "page_location_status": page_location_status,
        "element_types": element_types,
        "highlight_rect": None,
    }
    if page_location_status != "complete" or len(pages) != 1:
        return result
    rects = [_normalized_rect(element) for element in elements]
    if any(rect is None for rect in rects):
        return result
    left = min(rect["left"] for rect in rects)
    top = min(rect["top"] for rect in rects)
    right = max(rect["left"] + rect["width"] for rect in rects)
    bottom = max(rect["top"] + rect["height"] for rect in rects)
    result["highlight_rect"] = {
        "page": pages[0],
        "left": left,
        "top": top,
        "width": right - left,
        "height": bottom - top,
    }
    return result
