"""
monitor/sparkline.py

Pure-Python SVG sparkline generator. No Django imports, no DB access.
Called from views.py — not from templates directly.
"""

# Dot colour per RuleResult.Status value.
_COLOUR = {
    'OK':    '#22c55e',  # green  — matches --ok CSS var
    'FAIL':  '#f87171',  # red    — matches --fail CSS var
    'ERROR': '#fbbf24',  # amber  — matches --error CSS var
}
_COLOUR_UNKNOWN = '#6b7280'  # muted grey for any unrecognised status

_DOT_RADIUS = 3  # px


def status_dot_sparkline(
    statuses: list,
    width: int = 120,
    height: int = 16,
) -> str:
    """Return an inline SVG strip of coloured dots representing a status sequence.

    Args:
        statuses: list of status strings, oldest-first.
                  Expected values: 'OK', 'FAIL', 'ERROR'. Unknown values get a grey dot.
        width:    total SVG width in px (default 120).
        height:   total SVG height in px (default 16).

    Returns:
        Inline SVG string (no XML declaration, safe for mark_safe).
        Returns empty string when statuses is empty.
    """
    if not statuses:
        return ''

    n = len(statuses)
    cy = height // 2  # vertical centre

    # Distribute dots evenly: equal left/right margins, equal spacing between dots.
    # With n dots we get n gaps from left-edge to first dot and between dots and to right-edge.
    # Each gap = width / (n + 1) — keeps dots away from the SVG border by half a gap.
    gap = width / (n + 1)

    circles = []
    for i, status in enumerate(statuses):
        cx = gap * (i + 1)
        colour = _COLOUR.get(status, _COLOUR_UNKNOWN)
        circles.append(
            f'<circle cx="{cx:.1f}" cy="{cy}" r="{_DOT_RADIUS}" fill="{colour}"/>'
        )

    inner = ''.join(circles)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'style="display:inline-block;vertical-align:middle">'
        f'{inner}'
        f'</svg>'
    )
