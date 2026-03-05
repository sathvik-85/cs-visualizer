from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from scene_graph.schema import (
    SceneGraph, ArrayElement, BSTElement, GraphElement,
    DPTableElement, StackElement, QueueElement, TextBlock, BSTNode,
)

# ── Screen / zone constants ────────────────────────────────────────────────────
SCREEN_X_MIN, SCREEN_X_MAX = -7.0, 7.0
STAGE_Y_MIN,  STAGE_Y_MAX  = -2.2, 2.8
STAGE_W  = SCREEN_X_MAX - SCREEN_X_MIN   # 14.0
STAGE_H  = STAGE_Y_MAX  - STAGE_Y_MIN    # 5.0
STAGE_CX = 0.0
STAGE_CY = (STAGE_Y_MIN + STAGE_Y_MAX) / 2.0   # 0.3

CELL_SIZE   = 0.9
CELL_BUFF   = 0.1
NODE_RADIUS = 0.4
MIN_BUFF    = 0.3


class LayoutError(Exception):
    pass


@dataclass
class LayoutRect:
    cx: float
    cy: float
    width: float
    height: float
    scale: float = 1.0


@dataclass
class LayoutPlan:
    # step_id → element_id → LayoutRect (for every visible element that step)
    step_layouts: dict[int, dict[str, LayoutRect]] = field(default_factory=dict)
    # element_id → {node_id: (x, y)}  — absolute world coords
    bst_positions: dict[str, dict] = field(default_factory=dict)
    graph_positions: dict[str, dict] = field(default_factory=dict)


# ── Intrinsic size functions ────────────────────────────────────────────────────

def _size_array(n: int) -> tuple[float, float]:
    w = n * (CELL_SIZE + CELL_BUFF) - CELL_BUFF
    h = CELL_SIZE + 0.55   # cell + index label below
    return max(w, 1.0), h


def _bst_depth(node: Optional[BSTNode]) -> int:
    if node is None:
        return 0
    return 1 + max(_bst_depth(node.left), _bst_depth(node.right))


def _bst_leaf_count(node: Optional[BSTNode]) -> int:
    if node is None:
        return 0
    if node.left is None and node.right is None:
        return 1
    return _bst_leaf_count(node.left) + _bst_leaf_count(node.right)


def _size_bst(root: BSTNode) -> tuple[float, float]:
    depth = _bst_depth(root)
    leaves = max(1, _bst_leaf_count(root))
    node_spacing = NODE_RADIUS * 2 + 0.55
    w = max(leaves * node_spacing, 2.0)
    level_h = NODE_RADIUS * 2 + 0.75
    h = depth * level_h
    return w, h


def _size_graph(n: int) -> tuple[float, float]:
    radius = max(1.4, n * 0.38)
    side = radius * 2 + NODE_RADIUS * 2 + 0.4
    return side, side


def _size_dp_table(rows: int, cols: int) -> tuple[float, float]:
    cell = 0.7
    label_extra = 0.65
    return cols * cell + label_extra, rows * cell + label_extra


def _size_stack(n: int) -> tuple[float, float]:
    return 2.5, max(1, n) * 0.72 + 0.6


def _size_queue(n: int) -> tuple[float, float]:
    return max(1, n) * 0.95 + 0.6, 1.15


def _size_text_block(n_lines: int, font_size: int) -> tuple[float, float]:
    line_h = font_size / 72.0 * 2.0 + 0.18
    h = n_lines * line_h + 0.4
    w = min(11.0, 4.0 + font_size / 22.0 * 2.5)
    return w, h


def _compute_size(el) -> tuple[float, float]:
    if isinstance(el, ArrayElement):
        return _size_array(len(el.values))
    if isinstance(el, BSTElement):
        return _size_bst(el.root)
    if isinstance(el, GraphElement):
        return _size_graph(len(el.nodes))
    if isinstance(el, DPTableElement):
        return _size_dp_table(el.rows, el.cols)
    if isinstance(el, StackElement):
        return _size_stack(len(el.values))
    if isinstance(el, QueueElement):
        return _size_queue(len(el.values))
    if isinstance(el, TextBlock):
        return _size_text_block(len(el.lines), el.font_size)
    return 3.0, 2.0


# ── Stage partitioning ─────────────────────────────────────────────────────────

def _partition_stage(
    eids: list[str],
    sizes: dict[str, tuple[float, float]],
) -> dict[str, LayoutRect]:
    n = len(eids)
    if n == 0:
        return {}

    if n == 1:
        eid = eids[0]
        w, h = sizes[eid]
        return {eid: LayoutRect(STAGE_CX, STAGE_CY, w, h)}

    if n == 2:
        a, b = eids
        wa, ha = sizes[a]
        wb, hb = sizes[b]
        # If both elements are taller than wide (e.g. stacks), stack vertically
        if ha > wa and hb > wb:
            return {
                a: LayoutRect(STAGE_CX, STAGE_CY + STAGE_H / 4, wa, ha),
                b: LayoutRect(STAGE_CX, STAGE_CY - STAGE_H / 4, wb, hb),
            }
        # Otherwise split horizontally
        return {
            a: LayoutRect(-STAGE_W / 4, STAGE_CY, wa, ha),
            b: LayoutRect(+STAGE_W / 4, STAGE_CY, wb, hb),
        }

    if n <= 4:
        cols = 2
        half_w = STAGE_W / 2
        half_h = STAGE_H / 2
        positions = [
            (-half_w / 2, STAGE_CY + half_h / 2),
            (+half_w / 2, STAGE_CY + half_h / 2),
            (-half_w / 2, STAGE_CY - half_h / 2),
            (+half_w / 2, STAGE_CY - half_h / 2),
        ]
        result = {}
        for i, eid in enumerate(eids):
            cx, cy = positions[i]
            w, h = sizes[eid]
            result[eid] = LayoutRect(cx, cy, w, h)
        return result

    raise LayoutError(
        f"A step has {n} simultaneous visible elements (max 4). "
        "Split the step into smaller steps with fewer elements."
    )


def _clamp_to_stage(rect: LayoutRect) -> LayoutRect:
    w, h = rect.width, rect.height
    scale = 1.0
    max_w = STAGE_W * 0.91
    max_h = STAGE_H * 0.87

    if w > max_w or h > max_h:
        scale = min(max_w / w, max_h / h)
        w *= scale
        h *= scale

    hw = w / 2 + MIN_BUFF
    hh = h / 2 + MIN_BUFF
    cx = max(SCREEN_X_MIN + hw, min(SCREEN_X_MAX - hw, rect.cx))
    cy = max(STAGE_Y_MIN + hh, min(STAGE_Y_MAX - hh, rect.cy))

    return LayoutRect(cx, cy, w, h, scale)


# ── BST node positions ─────────────────────────────────────────────────────────

def _layout_bst_nodes(root: Optional[BSTNode], rect: LayoutRect) -> dict:
    depth = _bst_depth(root)
    if depth == 0:
        return {}
    level_h = rect.height / max(depth, 1)
    positions: dict = {}

    def recurse(node: Optional[BSTNode], lo: float, hi: float, y: float) -> None:
        if node is None:
            return
        cx = (lo + hi) / 2.0
        positions[node.id] = (cx, y)
        mid = (lo + hi) / 2.0
        recurse(node.left,  lo,  mid, y - level_h)
        recurse(node.right, mid, hi,  y - level_h)

    top_y = rect.cy + rect.height / 2.0 - NODE_RADIUS
    recurse(root, rect.cx - rect.width / 2.0, rect.cx + rect.width / 2.0, top_y)
    return positions


# ── Graph node positions ───────────────────────────────────────────────────────

def _layout_graph_nodes(el: GraphElement, rect: LayoutRect) -> dict:
    n = len(el.nodes)
    if n == 0:
        return {}
    radius = min(rect.width, rect.height) / 2.0 - NODE_RADIUS - 0.25
    radius = max(0.5, radius)
    positions: dict = {}
    for i, nid in enumerate(el.nodes):
        angle = 2.0 * math.pi * i / n - math.pi / 2.0
        positions[nid] = (
            rect.cx + radius * math.cos(angle),
            rect.cy + radius * math.sin(angle),
        )
    return positions


# ── Main entry ─────────────────────────────────────────────────────────────────

def compute_layout(scene: SceneGraph) -> LayoutPlan:
    plan = LayoutPlan()
    visible: set[str] = set()

    for step in scene.steps:
        # Process fade_out actions first (elements leave stage mid-step)
        for action in step.actions:
            if action.action == "fade_out":
                visible.discard(action.target_id)

        # Elements explicitly removed at end of step
        for eid in step.remove_elements:
            visible.discard(eid)

        # Newly introduced elements
        for eid in step.introduce_elements:
            if eid not in scene.elements:
                raise LayoutError(
                    f"Step {step.step_id}: element '{eid}' not declared in 'elements' dict"
                )
            visible.add(eid)

        # Validate action targets
        for action in step.actions:
            tid = getattr(action, "target_id", None)
            if tid and tid not in scene.elements:
                raise LayoutError(
                    f"Step {step.step_id}: action references unknown element '{tid}'"
                )

        if not visible:
            plan.step_layouts[step.step_id] = {}
            continue

        sizes = {eid: _compute_size(scene.elements[eid]) for eid in visible}
        rects = _partition_stage(list(visible), sizes)
        clamped = {eid: _clamp_to_stage(r) for eid, r in rects.items()}
        plan.step_layouts[step.step_id] = clamped

        # Compute internal positions for structured elements (once, on first appearance)
        for eid in visible:
            el = scene.elements[eid]
            if isinstance(el, BSTElement) and eid not in plan.bst_positions:
                plan.bst_positions[eid] = _layout_bst_nodes(el.root, clamped[eid])
            if isinstance(el, GraphElement) and eid not in plan.graph_positions:
                plan.graph_positions[eid] = _layout_graph_nodes(el, clamped[eid])

    return plan
