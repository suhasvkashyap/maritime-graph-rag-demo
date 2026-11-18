"""Theme-agnostic SVG rendering for the impact graph.

Renders the reconstructed chain (group -> operators -> vessels -> calls ->
berth/closure, calls -> shipments -> receiving chain) as a layered SVG. Uses
``currentColor`` and translucent fills so it works in Streamlit light and dark
themes without external assets.
"""

from __future__ import annotations

from typing import Any

NODE_W, NODE_H = 148, 44
COL_GAP, ROW_GAP = 56, 14
MARGIN = 16

# Column ranks for the layered layout.
RANKS = {
    "group": 0,
    "operator": 1,
    "vessel": 2,
    "call": 3,
    "berth": 4,
    "notice": 4,
    "shipment": 5,
    "recipient": 6,
}


def _esc(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _classify(name: str, hint: str | None) -> tuple[str, str]:
    """Return (rank_key, display_label) for a node name."""
    lowered = name.lower()
    if hint in RANKS and hint != "berth":
        return hint, name
    if lowered.startswith("syn-g"):
        return "group", name
    if lowered.startswith("syn-o"):
        return "operator", name
    if lowered.startswith("syn-v"):
        return "vessel", name
    if lowered.startswith("syn-c"):
        return "call", name
    if lowered.startswith("syn-n"):
        return "notice", name
    if lowered.startswith("syn-s"):
        return "shipment", name
    if lowered.startswith(("berth", "syn-b", "syn-p")):
        return "berth", name
    if "terminal" in lowered or lowered.startswith("pearl") or lowered.startswith("juniper"):
        return "recipient", name
    return "recipient", name


def build_graph_spec(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Assemble nodes/edges for the evidence-relationships view."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(name: str, hint: str | None = None, note: str | None = None) -> str:
        key, label = _classify(name, hint)
        if name not in nodes:
            nodes[name] = {"name": name, "rank": key, "note": note}
        elif note and not nodes[name].get("note"):
            nodes[name]["note"] = note
        return name

    for relationship in pipeline.get("relationships", []):
        source = relationship["source_entity"]
        target = relationship["target_entity"]
        if relationship["relationship"] == "operated_by":
            add_node(source, "vessel")
            add_node(target, "operator")
            edges.append({"source": source, "target": target, "label": "operated by"})
        elif relationship["relationship"] == "subsidiary_of":
            add_node(source, "operator")
            add_node(target, "group")
            edges.append({"source": source, "target": target, "label": "subsidiary of"})

    for call in pipeline.get("effective_calls", []):
        call_id = call["call_id"]
        vessel = call.get("vessel_id") or call.get("vessel")
        berth = call.get("berth_name") or call.get("berth_id")
        add_node(call_id, "call", note=call.get("window"))
        if vessel:
            add_node(vessel, "vessel")
            edges.append({"source": vessel, "target": call_id, "label": "planned call"})
        if berth:
            add_node(berth, "berth", note=call.get("port"))
            edges.append({"source": call_id, "target": berth, "label": "at berth"})

    notice = pipeline.get("notice")
    if notice:
        berth = notice.get("berth_name") or notice.get("berth_id")
        add_node(notice["notice_id"], "notice", note=notice.get("window"))
        if berth:
            add_node(berth, "berth")
            edges.append(
                {"source": notice["notice_id"], "target": berth, "label": "closes", "emphasis": True}
            )

    overlapping = {overlap["call_id"] for overlap in pipeline.get("overlaps", [])}
    for node in nodes.values():
        if node["rank"] == "call" and node["name"] in overlapping:
            node["overlap"] = True

    for row in pipeline.get("shipments", []):
        shipment = row.get("shipment_id")
        if not shipment:
            continue
        add_node(shipment, "shipment", note=row.get("description"))
        if row.get("call_id"):
            add_node(row["call_id"], "call")
            edges.append({"source": row["call_id"], "target": shipment, "label": "carries"})
        if row.get("recipient"):
            add_node(row["recipient"], "recipient")
            edges.append({"source": shipment, "target": row["recipient"], "label": "for"})
        if row.get("facility"):
            add_node(row["facility"], "recipient", note=row.get("receipt_deadline"))
            edges.append({"source": shipment, "target": row["facility"], "label": "received at"})

    return {"nodes": list(nodes.values()), "edges": edges}


def render_svg(spec: dict[str, Any]) -> str:
    nodes = spec["nodes"]
    edges = spec["edges"]
    if not nodes:
        return "<p>No graph data available.</p>"

    columns: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        columns.setdefault(RANKS[node["rank"]], []).append(node)

    positions: dict[str, tuple[int, int]] = {}
    max_rows = max(len(rows) for rows in columns.values())
    width = MARGIN * 2 + len(columns) * NODE_W + (len(columns) - 1) * COL_GAP
    height = MARGIN * 2 + max_rows * NODE_H + (max_rows - 1) * ROW_GAP + 30

    for display_col, col_index in enumerate(sorted(columns)):
        rows = sorted(columns[col_index], key=lambda n: n["name"])
        column_height = len(rows) * NODE_H + (len(rows) - 1) * ROW_GAP
        top_offset = MARGIN + max(0, (height - 30 - MARGIN - column_height) // 2)
        for row_index, node in enumerate(rows):
            x = MARGIN + display_col * (NODE_W + COL_GAP)
            y = top_offset + row_index * (NODE_H + ROW_GAP)
            positions[node["name"]] = (x, y)

    def node_center(name: str) -> tuple[int, int, int, int]:
        x, y = positions[name]
        return x + NODE_W // 2, y + NODE_H // 2, x, y

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" '
        'xmlns="http://www.w3.org/2000/svg" role="img">',
        "<defs><marker id=\"arrow\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" "
        "markerWidth=\"7\" markerHeight=\"7\" orient=\"auto-start-reverse\">"
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8a8f98"/></marker></defs>',
    ]
    for edge in edges:
        if edge["source"] not in positions or edge["target"] not in positions:
            continue
        sx, sy, _, _ = node_center(edge["source"])
        tx, ty, _, _ = node_center(edge["target"])
        # Start/end at box borders.
        dx, dy = tx - sx, ty - sy
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / length, dy / length
        x1, y1 = sx + ux * (NODE_W // 2 + 2), sy + uy * (NODE_H // 2 + 2)
        x2, y2 = tx - ux * (NODE_W // 2 + 4), ty - uy * (NODE_H // 2 + 4)
        emphasis = edge.get("emphasis")
        stroke = "#c95d2c" if emphasis else "#8a8f98"
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{2 if emphasis else 1.4}" marker-end="url(#arrow)"/>'
        )
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 4
        parts.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" font-size="10" text-anchor="middle" '
            f'fill="currentColor" opacity="0.75">{_esc(edge["label"])}</text>'
        )
    for name, (x, y) in positions.items():
        node = next(n for n in nodes if n["name"] == name)
        overlap = node.get("overlap")
        stroke = "#c95d2c" if overlap else "#8a8f98"
        stroke_width = 2.2 if overlap else 1.2
        parts.append(
            f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="9" '
            f'fill="rgba(128,128,128,0.10)" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        label = node["name"]
        note = node.get("note")
        if note:
            label = f"{label}"
            parts.append(
                f'<text x="{x + NODE_W / 2}" y="{y + 19}" font-size="11.5" font-weight="600" '
                f'text-anchor="middle" fill="currentColor">{_esc(label[:22])}</text>'
            )
            parts.append(
                f'<text x="{x + NODE_W / 2}" y="{y + 34}" font-size="9.5" '
                f'text-anchor="middle" fill="currentColor" opacity="0.7">{_esc(str(note)[:30])}</text>'
            )
        else:
            parts.append(
                f'<text x="{x + NODE_W / 2}" y="{y + NODE_H / 2 + 4}" font-size="11.5" '
                f'font-weight="600" text-anchor="middle" fill="currentColor">{_esc(label[:24])}</text>'
            )
        if overlap:
            parts.append(
                f'<text x="{x + NODE_W / 2}" y="{y + NODE_H + 12}" font-size="9" '
                f'text-anchor="middle" fill="#c95d2c" font-weight="700">OVERLAPS CLOSURE</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def render_impact_graph(pipeline: dict[str, Any]) -> tuple[str, str]:
    """Return (label, svg) for the best available graph view.

    Precedence: live extracted graph > evidence relationships > expected
    fixture graph. The label always states what the view actually shows.
    """
    for view in reversed(pipeline.get("graph_views", [])):
        if view.get("nodes"):
            return view.get("label_text", "Graph"), _render_graph_view(view)

    spec = build_graph_spec(pipeline)
    if not spec["nodes"]:
        return "No graph available", "<p>No relationship data was retrieved.</p>"
    label = "Evidence relationships: reconstructed from retrieved passages (source-backed)."
    return label, render_svg(spec)


def _render_graph_view(view: dict[str, Any]) -> str:
    """Render an extracted/fixture graph view (nodes + edges with types)."""
    nodes = view.get("nodes", [])
    edges = view.get("edges", [])
    if not nodes:
        return "<p>No graph data available.</p>"
    positions: dict[str, tuple[int, int]] = {}
    columns: dict[int, list[str]] = {}
    names = [n["name"] for n in nodes]
    for name in names:
        rank_key, _ = _classify(name, None)
        columns.setdefault(RANKS[rank_key], []).append(name)
    max_rows = max(len(rows) for rows in columns.values())
    width = MARGIN * 2 + len(columns) * NODE_W + (len(columns) - 1) * COL_GAP
    height = MARGIN * 2 + max_rows * NODE_H + (max_rows - 1) * ROW_GAP
    for display_col, col_index in enumerate(sorted(columns)):
        rows = sorted(columns[col_index])
        column_height = len(rows) * NODE_H + (len(rows) - 1) * ROW_GAP
        top_offset = MARGIN + max(0, (height - column_height) // 2)
        for row_index, name in enumerate(rows):
            x = MARGIN + display_col * (NODE_W + COL_GAP)
            y = top_offset + row_index * (NODE_H + ROW_GAP)
            positions[name] = (x, y)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" '
        'xmlns="http://www.w3.org/2000/svg" role="img">',
        "<defs><marker id=\"arrow2\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" "
        "markerWidth=\"7\" markerHeight=\"7\" orient=\"auto-start-reverse\">"
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8a8f98"/></marker></defs>',
    ]
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source not in positions or target not in positions:
            continue
        sx, sy = positions[source]
        tx, ty = positions[target]
        parts.append(
            f'<line x1="{sx + NODE_W / 2}" y1="{sy + NODE_H / 2}" x2="{tx + NODE_W / 2}" '
            f'y2="{ty + NODE_H / 2}" stroke="#8a8f98" stroke-width="1.4" marker-end="url(#arrow2)" opacity="0.7"/>'
        )
        mx, my = (sx + tx) / 2 + NODE_W / 2, (sy + ty) / 2 + NODE_H / 2
        parts.append(
            f'<text x="{mx:.0f}" y="{my:.0f}" font-size="9.5" text-anchor="middle" '
            f'fill="currentColor" opacity="0.7">{_esc(edge.get("relationship", ""))}</text>'
        )
    for name, (x, y) in positions.items():
        parts.append(
            f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="9" '
            f'fill="rgba(128,128,128,0.10)" stroke="#8a8f98" stroke-width="1.2"/>'
        )
        node = next(n for n in nodes if n["name"] == name)
        type_labels = ", ".join(node.get("type_labels") or [])
        parts.append(
            f'<text x="{x + NODE_W / 2}" y="{y + 19}" font-size="11" font-weight="600" '
            f'text-anchor="middle" fill="currentColor">{_esc(name[:22])}</text>'
        )
        parts.append(
            f'<text x="{x + NODE_W / 2}" y="{y + 34}" font-size="9" text-anchor="middle" '
            f'fill="currentColor" opacity="0.7">{_esc(type_labels[:30])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
