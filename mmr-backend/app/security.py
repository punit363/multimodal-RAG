"""Input and output safety helpers for document ingestion."""

import nh3


TABLE_TAGS = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    "p",
    "br",
    "strong",
    "em",
    "span",
}
TABLE_ATTRIBUTES = {
    "table": {"summary"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "col": {"span"},
    "colgroup": {"span"},
}


def sanitize_table_html(value: str) -> str:
    """Keep table structure while removing scripts, handlers, styles, and URLs."""
    return nh3.clean(
        value or "",
        tags=TABLE_TAGS,
        attributes=TABLE_ATTRIBUTES,
        url_schemes=set(),
        strip_comments=True,
    )
