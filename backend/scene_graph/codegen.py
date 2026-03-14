"""
Converts a SceneGraph + LayoutPlan into valid Manim Python code.
All element positions come from the layout engine — the LLM never picks coordinates.
"""
from __future__ import annotations
import os as _os
from typing import Optional

# Absolute path to the backend/ directory — embedded in generated code so the
# scene file can import KokoroService regardless of where Manim runs it from.
_BACKEND_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

from scene_graph.schema import (
    SceneGraph, Step, AnyAction,
    ArrayElement, BSTElement, GraphElement, DPTableElement,
    StackElement, QueueElement, TextBlock,
    HighlightAction, SwapAction, CompareAction, MarkVisitedAction,
    SetValueAction, PushAction, PopAction, FadeOutAction,
)
from scene_graph.layout import LayoutPlan, LayoutRect, NODE_RADIUS


# Color palette keys → hex values
PALETTE = {
    "PRIMARY":   "#4A90D9",
    "SECONDARY": "#50C878",
    "ACCENT":    "#F5A623",
    "HIGHLIGHT": "#E74C3C",
    "MUTED":     "#7F8C8D",
    "TEXT_COL":  "#ECF0F1",
    "BG":        "#1a1a2e",
}


def _safe_id(eid: str) -> str:
    """Convert element id to a valid Python identifier prefix."""
    return eid.replace("-", "_").replace(" ", "_")


def _fcoord(x: float, y: float) -> str:
    return f"np.array([{x:.3f}, {y:.3f}, 0])"


class _Emitter:
    def __init__(self) -> None:
        self._lines: list[str] = []
        self._level = 0

    def emit(self, line: str = "") -> None:
        if line:
            self._lines.append("    " * self._level + line)
        else:
            self._lines.append("")

    def indent(self) -> None:
        self._level += 1

    def dedent(self) -> None:
        self._level -= 1

    def result(self) -> str:
        return "\n".join(self._lines)


class ManimCodeGenerator:
    def __init__(self, scene: SceneGraph, plan: LayoutPlan) -> None:
        self.scene = scene
        self.plan = plan
        self._e = _Emitter()

        # State: which group variable represents each element id
        self._group_var: dict[str, str] = {}

        # Arrays: track Python list var for cell-level ops (swap etc.)
        self._arr_list_var: dict[str, str] = {}

        # BST/graph: track dict var name for node → mobject lookup
        self._bst_nodes_var: dict[str, str] = {}
        self._graph_nodes_var: dict[str, str] = {}
        self._graph_labels_var: dict[str, str] = {}

        # DP tables: 2D list var name (list of rows, each a list of cell VGroups)
        self._dp_cells_var: dict[str, str] = {}

        # Stacks/queues: Python list var tracking live item VGroups
        self._sq_list_var: dict[str, str] = {}
        self._sq_item_count: dict[str, int] = {}  # for unique var names

        # Caption management
        self._caption_var: Optional[str] = None
        self._caption_count = 0

        # Track which elements are currently visible
        self._visible: set[str] = set()

    # ── Public entry ───────────────────────────────────────────────────────────

    def generate(self) -> str:
        e = self._e
        self._emit_header()
        e.emit("class GeneratedScene(VoiceoverScene):")
        e.indent()
        e.emit("def construct(self):")
        e.indent()
        e.emit("self.set_speech_service(KokoroService())")
        e.emit('self.camera.background_color = "#1a1a2e"')
        e.emit()

        # Color palette constants (inside construct for clarity)
        e.emit("PRIMARY   = \"#4A90D9\"")
        e.emit("SECONDARY = \"#50C878\"")
        e.emit("ACCENT    = \"#F5A623\"")
        e.emit("HIGHLIGHT = \"#E74C3C\"")
        e.emit("MUTED     = \"#7F8C8D\"")
        e.emit("TEXT_COL  = \"#ECF0F1\"")
        e.emit()

        # Title
        title = self.scene.title.replace('"', "'")
        e.emit(f"title = Text(\"{title}\", font_size=36, color=TEXT_COL, weight=BOLD)")
        e.emit("title.to_edge(UP, buff=0.2)")
        e.emit("self.play(Write(title), run_time=0.8)")
        e.emit("self.wait(0.3)")
        e.emit()

        for step in self.scene.steps:
            self._emit_step(step)

        # Done screen
        self._emit_done()

        e.dedent()  # construct
        e.dedent()  # class
        return e.result()

    # ── Header ────────────────────────────────────────────────────────────────

    def _emit_header(self) -> None:
        e = self._e
        e.emit("from manim import *")
        e.emit("from manim_voiceover import VoiceoverScene")
        e.emit("from services.kokoro_service import KokoroService")
        e.emit("import numpy as np")
        e.emit()

    # ── Step ──────────────────────────────────────────────────────────────────

    def _emit_step(self, step: Step) -> None:
        e = self._e
        voiceover = step.voiceover.replace('"', "'")
        e.emit(f"with self.voiceover(\"{voiceover}\"):")
        e.indent()

        # Caption: fade out old, fade in new
        self._caption_count += 1
        cap_var = f"caption{self._caption_count}"
        if self._caption_var:
            e.emit(f"self.play(FadeOut({self._caption_var}), run_time=0.4)")
        caption_text = step.caption.replace('"', "'")
        e.emit(f"{cap_var} = Text(\"{caption_text}\", font_size=22, color=ACCENT)")
        e.emit(f"{cap_var}.to_edge(DOWN, buff=0.3)")
        e.emit(f"self.play(FadeIn({cap_var}), run_time=0.4)")
        self._caption_var = cap_var

        # Get layout for this step
        layout = self.plan.step_layouts.get(step.step_id, {})

        # Introduce new elements
        for eid in step.introduce_elements:
            if eid in self.scene.elements:
                rect = layout.get(eid)
                if rect:
                    self._emit_element_creation(eid, rect)
                    self._visible.add(eid)

        # Actions
        for action in step.actions:
            self._emit_action(action, layout)

        # Remove elements at end of step
        for eid in step.remove_elements:
            if eid in self._group_var:
                e.emit(f"self.play(FadeOut({self._group_var[eid]}), run_time=0.5)")
                self._visible.discard(eid)

        e.dedent()
        e.emit("self.wait(0.35)")
        e.emit()

    # ── Element creation ───────────────────────────────────────────────────────

    def _emit_element_creation(self, eid: str, rect: LayoutRect) -> None:
        el = self.scene.elements[eid]
        if isinstance(el, ArrayElement):
            self._emit_array(eid, el, rect)
        elif isinstance(el, BSTElement):
            self._emit_bst(eid, el, rect)
        elif isinstance(el, GraphElement):
            self._emit_graph(eid, el, rect)
        elif isinstance(el, DPTableElement):
            self._emit_dp_table(eid, el, rect)
        elif isinstance(el, StackElement):
            self._emit_stack(eid, el, rect)
        elif isinstance(el, QueueElement):
            self._emit_queue(eid, el, rect)
        elif isinstance(el, TextBlock):
            self._emit_text_block(eid, el, rect)

    def _emit_array(self, eid: str, el: ArrayElement, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        scale = rect.scale
        cell_side = round(0.9 * scale, 4)
        cell_buff = round(0.1 * scale, 4)
        font_size = max(16, int(28 * scale))
        idx_font  = max(12, int(16 * scale))
        idx_buff  = round(0.15 * scale, 4)

        # Build cells
        list_var  = f"{pid}_cells_list"
        cells_var = f"{pid}_cells"
        idx_var   = f"{pid}_indices"
        grp_var   = f"{pid}_group"

        e.emit(f"{list_var} = []")
        e.emit(f"for _v in {el.values}:")
        e.indent()
        e.emit(f"_sq = Square(side_length={cell_side}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
        e.emit(f"_lbl = Text(str(_v), font_size={font_size}, color=TEXT_COL).move_to(_sq)")
        e.emit(f"{list_var}.append(VGroup(_sq, _lbl))")
        e.dedent()
        e.emit(f"{cells_var} = VGroup(*{list_var})")
        e.emit(f"{cells_var}.arrange(RIGHT, buff={cell_buff})")
        e.emit(f"{cells_var}.move_to({_fcoord(rect.cx, rect.cy)})")
        e.emit(f"{idx_var} = VGroup(*[")
        e.indent()
        e.emit(f"Text(str(_i), font_size={idx_font}, color=MUTED).next_to({list_var}[_i], DOWN, buff={idx_buff})")
        e.emit(f"for _i in range(len({list_var}))")
        e.dedent()
        e.emit("])")
        e.emit(f"{grp_var} = VGroup({cells_var}, {idx_var})")

        # Optional label above
        if el.label:
            lbl_font = max(16, int(20 * scale))
            lbl_buff = round(0.25 * scale, 4)
            e.emit(f"{pid}_label = Text(\"{el.label}\", font_size={lbl_font}, color=MUTED)")
            e.emit(f"{pid}_label.next_to({cells_var}, UP, buff={lbl_buff})")
            e.emit(f"{grp_var}.add({pid}_label)")

        e.emit(f"self.play(AnimationGroup(*[FadeIn(_c, shift=UP*0.2) for _c in {list_var}],")
        e.emit(f"                         FadeIn({idx_var}), lag_ratio=0.08), run_time=1.0)")

        self._arr_list_var[eid] = list_var
        self._group_var[eid] = grp_var

    def _emit_bst(self, eid: str, el: BSTElement, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        node_positions = self.plan.bst_positions.get(eid, {})
        scale = rect.scale
        radius = round(NODE_RADIUS * scale, 4)
        font_size = max(14, int(22 * scale))

        nodes_var = f"{pid}_nodes"
        edges_var = f"{pid}_edges"
        grp_var   = f"{pid}_group"

        e.emit(f"{nodes_var} = {{}}")
        e.emit(f"{edges_var} = VGroup()")

        # Collect all nodes (BFS)
        all_nodes: list = []
        queue = [el.root]
        while queue:
            node = queue.pop(0)
            if node is None:
                continue
            all_nodes.append(node)
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)

        for node in all_nodes:
            pos = node_positions.get(node.id)
            if pos is None:
                continue
            x, y = pos
            nvar = f"{pid}_n{_safe_id(str(node.id))}"
            val_str = str(node.value).replace('"', "'")
            e.emit(f"{nvar}_c = Circle(radius={radius}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
            e.emit(f"{nvar}_c.move_to({_fcoord(x, y)})")
            e.emit(f"{nvar}_t = Text(\"{val_str}\", font_size={font_size}, color=TEXT_COL).move_to({nvar}_c)")
            e.emit(f"{nvar} = VGroup({nvar}_c, {nvar}_t)")
            e.emit(f"{nodes_var}[{repr(node.id)}] = {nvar}")

        # Edges
        def emit_edges(node):
            if node is None:
                return
            for child in [node.left, node.right]:
                if child is None:
                    continue
                if node.id in node_positions and child.id in node_positions:
                    pvar = f"{pid}_n{_safe_id(str(node.id))}"
                    cvar = f"{pid}_n{_safe_id(str(child.id))}"
                    e.emit(f"{edges_var}.add(Line({pvar}_c.get_bottom(), {cvar}_c.get_top(), color=MUTED, buff=0.05))")
                emit_edges(child)

        emit_edges(el.root)

        e.emit(f"{grp_var} = VGroup({edges_var}, *list({nodes_var}.values()))")
        e.emit(f"self.play(FadeIn({edges_var}), AnimationGroup(")
        e.indent()
        e.emit(f"*[FadeIn(_n, shift=UP*0.15) for _n in {nodes_var}.values()], lag_ratio=0.06), run_time=1.2)")
        e.dedent()

        self._bst_nodes_var[eid] = nodes_var
        self._group_var[eid] = grp_var

    def _emit_graph(self, eid: str, el: GraphElement, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        node_positions = self.plan.graph_positions.get(eid, {})
        scale = rect.scale
        radius = round(NODE_RADIUS * scale, 4)
        font_size = max(14, int(22 * scale))

        nodes_var  = f"{pid}_nodes"
        labels_var = f"{pid}_labels"
        edges_var  = f"{pid}_edges"
        grp_var    = f"{pid}_group"

        e.emit(f"{nodes_var}  = {{}}")
        e.emit(f"{labels_var} = {{}}")
        e.emit(f"{edges_var}  = VGroup()")

        for nid in el.nodes:
            pos = node_positions.get(nid)
            if pos is None:
                continue
            x, y = pos
            nvar = f"{pid}_n{_safe_id(str(nid))}"
            e.emit(f"{nvar} = Circle(radius={radius}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
            e.emit(f"{nvar}.move_to({_fcoord(x, y)})")
            e.emit(f"{nodes_var}[{repr(nid)}] = {nvar}")
            lvar = f"{pid}_l{_safe_id(str(nid))}"
            e.emit(f"{lvar} = Text(\"{nid}\", font_size={font_size}, color=TEXT_COL).move_to({nvar})")
            e.emit(f"{labels_var}[{repr(nid)}] = {lvar}")

        for edge in el.edges:
            fn, tn = edge.from_node, edge.to_node
            if fn not in node_positions or tn not in node_positions:
                continue
            fnvar = f"{pid}_n{_safe_id(str(fn))}"
            tnvar = f"{pid}_n{_safe_id(str(tn))}"
            if edge.directed:
                # Use max_tip_length_to_length_ratio so arrows don't look huge on short edges
                e.emit(f"{edges_var}.add(Arrow(start={fnvar}.get_center(), end={tnvar}.get_center(), color=MUTED, tip_length=0.18, max_tip_length_to_length_ratio=0.4, stroke_width=2))")
            else:
                e.emit(f"{edges_var}.add(Line({fnvar}.get_center(), {tnvar}.get_center(), color=MUTED, stroke_width=2))")
            if edge.weight is not None:
                e.emit(f"_ew = Text(\"{edge.weight}\", font_size={max(12, int(16 * scale))}, color=ACCENT)")
                e.emit(f"_ew.move_to(({fnvar}.get_center() + {tnvar}.get_center()) / 2 + UP * 0.22)")
                e.emit(f"{edges_var}.add(_ew)")

        e.emit(f"{grp_var} = VGroup({edges_var}, *list({nodes_var}.values()), *list({labels_var}.values()))")
        e.emit(f"self.play(FadeIn({edges_var}), AnimationGroup(")
        e.indent()
        e.emit(f"*[FadeIn(_n, shift=UP*0.1) for _n in {nodes_var}.values()],")
        e.emit(f"*[FadeIn(_l) for _l in {labels_var}.values()], lag_ratio=0.08), run_time=1.2)")
        e.dedent()

        self._graph_nodes_var[eid] = nodes_var
        self._graph_labels_var[eid] = labels_var
        self._group_var[eid] = grp_var

    def _emit_dp_table(self, eid: str, el: DPTableElement, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        scale = rect.scale
        cell_size = round(0.7 * scale, 4)
        font_size = max(12, int(18 * scale))

        cells_var = f"{pid}_cells"
        grp_var   = f"{pid}_group"

        e.emit(f"{cells_var} = []")
        e.emit(f"_dp_group = VGroup()")

        rows = el.rows
        cols = el.cols
        init = el.initial_values

        e.emit(f"for _r in range({rows}):")
        e.indent()
        e.emit(f"_row = []")
        e.emit(f"for _c in range({cols}):")
        e.indent()
        e.emit(f"_sq = Square(side_length={cell_size}, color=MUTED, fill_color=BG, fill_opacity=1)")
        # Initial value
        if init:
            e.emit(f"_init_vals = {init}")
            e.emit(f"_iv = _init_vals[_r][_c] if _r < len(_init_vals) and _c < len(_init_vals[_r]) else ''")
            e.emit(f"_lbl = Text(str(_iv), font_size={font_size}, color=TEXT_COL).move_to(_sq)")
        else:
            e.emit(f"_lbl = Text('', font_size={font_size}, color=TEXT_COL).move_to(_sq)")
        e.emit(f"_row.append(VGroup(_sq, _lbl))")
        e.emit(f"_dp_group.add(VGroup(_sq, _lbl))")
        e.dedent()
        e.emit(f"{cells_var}.append(_row)")
        e.dedent()

        e.emit(f"_dp_group.arrange_in_grid(rows={rows}, cols={cols}, buff=0)")
        e.emit(f"_dp_group.move_to({_fcoord(rect.cx, rect.cy)})")

        # Row labels
        if el.row_labels:
            e.emit(f"_rl_list = {el.row_labels}")
            e.emit(f"for _ri, _rl in enumerate(_rl_list):")
            e.indent()
            e.emit(f"_rl_txt = Text(str(_rl), font_size={max(12, int(14 * scale))}, color=MUTED)")
            e.emit(f"_rl_txt.next_to({cells_var}[_ri][0][0], LEFT, buff=0.1)")
            e.emit(f"_dp_group.add(_rl_txt)")
            e.dedent()

        # Col labels
        if el.col_labels:
            e.emit(f"_cl_list = {el.col_labels}")
            e.emit(f"for _ci, _cl in enumerate(_cl_list):")
            e.indent()
            e.emit(f"_cl_txt = Text(str(_cl), font_size={max(12, int(14 * scale))}, color=MUTED)")
            e.emit(f"_cl_txt.next_to({cells_var}[0][_ci][0], UP, buff=0.1)")
            e.emit(f"_dp_group.add(_cl_txt)")
            e.dedent()

        e.emit(f"{grp_var} = _dp_group")
        e.emit(f"self.play(FadeIn({grp_var}, shift=UP*0.2), run_time=0.8)")

        self._dp_cells_var[eid] = cells_var
        self._group_var[eid] = grp_var

    def _emit_stack(self, eid: str, el: StackElement, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        scale = rect.scale
        item_w = round(2.0 * scale, 4)
        item_h = round(0.65 * scale, 4)
        font_size = max(14, int(22 * scale))
        buff = round(0.04 * scale, 4)

        list_var = f"{pid}_items_list"
        grp_var  = f"{pid}_group"
        count = len(el.values)

        e.emit(f"{list_var} = []")
        e.emit(f"for _v in {list(el.values)}:")
        e.indent()
        e.emit(f"_r = Rectangle(width={item_w}, height={item_h}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
        e.emit(f"_t = Text(str(_v), font_size={font_size}, color=TEXT_COL).move_to(_r)")
        e.emit(f"{list_var}.append(VGroup(_r, _t))")
        e.dedent()

        items_vg = f"{pid}_items_vg"
        e.emit(f"{items_vg} = VGroup(*{list_var}) if {list_var} else VGroup()")
        e.emit(f"if {list_var}: {items_vg}.arrange(UP, buff={buff})")
        lbl_font = max(14, int(18 * scale))
        e.emit(f"{pid}_lbl = Text(\"{el.label}\", font_size={lbl_font}, color=MUTED)")
        e.emit(f"{pid}_lbl.next_to({items_vg} if {list_var} else VGroup(), UP, buff=0.15)")
        e.emit(f"{grp_var} = VGroup({items_vg}, {pid}_lbl)")
        e.emit(f"{grp_var}.move_to({_fcoord(rect.cx, rect.cy)})")
        e.emit(f"self.play(FadeIn({grp_var}, shift=RIGHT*0.2), run_time=0.8)")

        self._sq_list_var[eid] = list_var
        self._sq_item_count[eid] = count
        self._group_var[eid] = grp_var

    def _emit_queue(self, eid: str, el: QueueElement, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        scale = rect.scale
        item_w = round(0.85 * scale, 4)
        item_h = round(0.65 * scale, 4)
        font_size = max(14, int(22 * scale))
        buff = round(0.04 * scale, 4)

        list_var = f"{pid}_items_list"
        grp_var  = f"{pid}_group"

        e.emit(f"{list_var} = []")
        e.emit(f"for _v in {list(el.values)}:")
        e.indent()
        e.emit(f"_r = Rectangle(width={item_w}, height={item_h}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
        e.emit(f"_t = Text(str(_v), font_size={font_size}, color=TEXT_COL).move_to(_r)")
        e.emit(f"{list_var}.append(VGroup(_r, _t))")
        e.dedent()

        items_vg = f"{pid}_items_vg"
        e.emit(f"{items_vg} = VGroup(*{list_var}) if {list_var} else VGroup()")
        if el.values:
            e.emit(f"{items_vg}.arrange(RIGHT, buff={buff})")
        lbl_font = max(14, int(18 * scale))
        e.emit(f"{pid}_lbl = Text(\"{el.label}\", font_size={lbl_font}, color=MUTED)")
        e.emit(f"{pid}_lbl.next_to({items_vg} if {list_var} else VGroup(), UP, buff=0.15)")
        e.emit(f"{grp_var} = VGroup({items_vg}, {pid}_lbl)")
        e.emit(f"{grp_var}.move_to({_fcoord(rect.cx, rect.cy)})")
        e.emit(f"self.play(FadeIn({grp_var}, shift=RIGHT*0.2), run_time=0.8)")

        self._sq_list_var[eid] = list_var
        self._sq_item_count[eid] = len(el.values)
        self._group_var[eid] = grp_var

    def _emit_text_block(self, eid: str, el: TextBlock, rect: LayoutRect) -> None:
        e = self._e
        pid = _safe_id(eid)
        scale = rect.scale
        font_size = max(14, int(el.font_size * scale))
        buff = round(0.18 * scale, 4)

        texts: list[str] = []
        for i, line in enumerate(el.lines):
            line_escaped = line.replace('"', "'")
            tvar = f"{pid}_line{i}"
            e.emit(f"{tvar} = Text(\"{line_escaped}\", font_size={font_size}, color=TEXT_COL)")
            texts.append(tvar)

        grp_var = f"{pid}_group"
        e.emit(f"{grp_var} = VGroup({', '.join(texts)})")
        e.emit(f"{grp_var}.arrange(DOWN, aligned_edge=LEFT, buff={buff})")
        e.emit(f"{grp_var}.move_to({_fcoord(rect.cx, rect.cy)})")
        e.emit(f"self.play(Write({grp_var}), run_time=1.0)")

        self._group_var[eid] = grp_var

    # ── Actions ────────────────────────────────────────────────────────────────

    def _emit_action(self, action: AnyAction, layout: dict[str, LayoutRect]) -> None:
        e = self._e
        if isinstance(action, HighlightAction):
            self._emit_highlight(action)
        elif isinstance(action, SwapAction):
            self._emit_swap(action)
        elif isinstance(action, CompareAction):
            self._emit_compare(action)
        elif isinstance(action, MarkVisitedAction):
            self._emit_mark_visited(action)
        elif isinstance(action, SetValueAction):
            self._emit_set_value(action)
        elif isinstance(action, PushAction):
            self._emit_push(action, layout)
        elif isinstance(action, PopAction):
            self._emit_pop(action)
        elif isinstance(action, FadeOutAction):
            self._emit_fade_out_action(action)

    def _emit_highlight(self, action: HighlightAction) -> None:
        e = self._e
        eid = action.target_id
        color = action.color if action.color in PALETTE else "HIGHLIGHT"
        el = self.scene.elements.get(eid)

        if isinstance(el, ArrayElement) and eid in self._arr_list_var:
            lv = self._arr_list_var[eid]
            if action.indices:
                anims = ", ".join(
                    f"{lv}[{i}].animate.set_color({color})"
                    for i in action.indices
                )
                e.emit(f"self.play({anims}, run_time=0.5)")
            else:
                # Highlight whole array
                e.emit(f"self.play(*[_c.animate.set_color({color}) for _c in {lv}], run_time=0.5)")

        elif isinstance(el, BSTElement) and eid in self._bst_nodes_var:
            nv = self._bst_nodes_var[eid]
            if action.indices:
                # indices treated as node ids (index into nodes list)
                pass
            else:
                e.emit(f"self.play(*[Indicate(_n, color={color}, scale_factor=1.2) for _n in {nv}.values()], run_time=0.6)")

        elif isinstance(el, GraphElement) and eid in self._graph_nodes_var:
            nv = self._graph_nodes_var[eid]
            if action.indices:
                node_keys = [repr(el.nodes[i]) for i in action.indices if i < len(el.nodes)]
                for k in node_keys:
                    e.emit(f"self.play(Indicate({nv}[{k}], color={color}, scale_factor=1.3), run_time=0.5)")
            else:
                e.emit(f"self.play(*[Indicate(_n, color={color}, scale_factor=1.2) for _n in {nv}.values()], run_time=0.6)")

        elif eid in self._group_var:
            gv = self._group_var[eid]
            e.emit(f"self.play(Indicate({gv}, color={color}, scale_factor=1.1), run_time=0.5)")

    def _emit_swap(self, action: SwapAction) -> None:
        e = self._e
        eid = action.target_id
        if eid not in self._arr_list_var:
            return
        lv = self._arr_list_var[eid]
        i, j = action.index_a, action.index_b
        e.emit(f"_p{i}, _p{j} = {lv}[{i}].get_center().copy(), {lv}[{j}].get_center().copy()")
        e.emit(f"self.play({lv}[{i}].animate.move_to(_p{j}), {lv}[{j}].animate.move_to(_p{i}), run_time=0.9)")
        e.emit(f"{lv}[{i}], {lv}[{j}] = {lv}[{j}], {lv}[{i}]")

    def _emit_compare(self, action: CompareAction) -> None:
        e = self._e
        eid = action.target_id
        if eid not in self._arr_list_var:
            return
        lv = self._arr_list_var[eid]
        anims = ", ".join(
            f"Indicate({lv}[{i}], color=ACCENT, scale_factor=1.25)"
            for i in action.indices
        )
        e.emit(f"self.play({anims}, run_time=0.5)")
        e.emit("self.wait(0.2)")

    def _emit_mark_visited(self, action: MarkVisitedAction) -> None:
        e = self._e
        eid = action.target_id
        el = self.scene.elements.get(eid)

        if isinstance(el, GraphElement) and eid in self._graph_nodes_var:
            nv = self._graph_nodes_var[eid]
            for nid in action.node_ids:
                e.emit(f"if {repr(nid)} in {nv}:")
                e.indent()
                e.emit(f"self.play({nv}[{repr(nid)}].animate.set_color(SECONDARY), run_time=0.4)")
                e.dedent()

        elif isinstance(el, BSTElement) and eid in self._bst_nodes_var:
            nv = self._bst_nodes_var[eid]
            for nid in action.node_ids:
                e.emit(f"if {repr(nid)} in {nv}:")
                e.indent()
                e.emit(f"self.play({nv}[{repr(nid)}].animate.set_color(SECONDARY), run_time=0.4)")
                e.dedent()

    def _emit_set_value(self, action: SetValueAction) -> None:
        e = self._e
        eid = action.target_id
        if eid not in self._dp_cells_var:
            return
        cv = self._dp_cells_var[eid]
        val = str(action.value).replace('"', "'")
        row, col = action.row, action.col
        # Replace the label inside the cell VGroup (index 1 is the Text)
        e.emit(f"_new_lbl = Text(\"{val}\", font_size=18, color=PRIMARY)")
        e.emit(f"_new_lbl.move_to({cv}[{row}][{col}][0])")
        e.emit(f"self.play(ReplacementTransform({cv}[{row}][{col}][1], _new_lbl), run_time=0.5)")
        e.emit(f"{cv}[{row}][{col}] = VGroup({cv}[{row}][{col}][0], _new_lbl)")
        e.emit(f"self.play(Indicate({cv}[{row}][{col}], color=ACCENT), run_time=0.3)")

    def _emit_push(self, action: PushAction, layout: dict[str, LayoutRect]) -> None:
        e = self._e
        eid = action.target_id
        el = self.scene.elements.get(eid)
        if eid not in self._sq_list_var:
            return
        lv = self._sq_list_var[eid]
        count = self._sq_item_count.get(eid, 0)
        pid = _safe_id(eid)
        ivar = f"{pid}_new_item{count}"
        val = str(action.value).replace('"', "'")
        rect = layout.get(eid)

        if isinstance(el, StackElement):
            scale = rect.scale if rect else 1.0
            iw = round(2.0 * scale, 4)
            ih = round(0.65 * scale, 4)
            fs = max(14, int(22 * scale))
            e.emit(f"_r = Rectangle(width={iw}, height={ih}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
            e.emit(f"_t = Text(\"{val}\", font_size={fs}, color=TEXT_COL).move_to(_r)")
            e.emit(f"{ivar} = VGroup(_r, _t)")
            e.emit(f"if {lv}:")
            e.indent()
            e.emit(f"{ivar}.next_to({lv}[-1], UP, buff=0.04)")
            e.dedent()
            e.emit(f"else:")
            e.indent()
            e.emit(f"{ivar}.move_to({_fcoord(rect.cx if rect else 0, rect.cy if rect else 0)})")
            e.dedent()
            e.emit(f"self.play(FadeIn({ivar}, shift=UP*0.3), run_time=0.5)")
            e.emit(f"{lv}.append({ivar})")

        elif isinstance(el, QueueElement):
            scale = rect.scale if rect else 1.0
            iw = round(0.85 * scale, 4)
            ih = round(0.65 * scale, 4)
            fs = max(14, int(22 * scale))
            e.emit(f"_r = Rectangle(width={iw}, height={ih}, color=PRIMARY, fill_color=BG, fill_opacity=1)")
            e.emit(f"_t = Text(\"{val}\", font_size={fs}, color=TEXT_COL).move_to(_r)")
            e.emit(f"{ivar} = VGroup(_r, _t)")
            e.emit(f"if {lv}:")
            e.indent()
            e.emit(f"{ivar}.next_to({lv}[-1], RIGHT, buff=0.04)")
            e.dedent()
            e.emit(f"else:")
            e.indent()
            e.emit(f"{ivar}.move_to({_fcoord(rect.cx if rect else 0, rect.cy if rect else 0)})")
            e.dedent()
            e.emit(f"self.play(FadeIn({ivar}, shift=RIGHT*0.3), run_time=0.5)")
            e.emit(f"{lv}.append({ivar})")

        self._sq_item_count[eid] = count + 1

    def _emit_pop(self, action: PopAction) -> None:
        e = self._e
        eid = action.target_id
        if eid not in self._sq_list_var:
            return
        lv = self._sq_list_var[eid]
        el = self.scene.elements.get(eid)
        if isinstance(el, StackElement):
            # Pop from top (last item)
            e.emit(f"if {lv}:")
            e.indent()
            e.emit(f"_popped = {lv}.pop()")
            e.emit(f"self.play(FadeOut(_popped, shift=UP*0.3), run_time=0.4)")
            e.dedent()
        elif isinstance(el, QueueElement):
            # Dequeue from front (first item)
            e.emit(f"if {lv}:")
            e.indent()
            e.emit(f"_dequeued = {lv}.pop(0)")
            e.emit(f"self.play(FadeOut(_dequeued, shift=LEFT*0.3), run_time=0.4)")
            e.dedent()

    def _emit_fade_out_action(self, action: FadeOutAction) -> None:
        e = self._e
        eid = action.target_id
        if eid in self._group_var:
            e.emit(f"self.play(FadeOut({self._group_var[eid]}), run_time=0.5)")
            self._visible.discard(eid)

    # ── Done screen ────────────────────────────────────────────────────────────

    def _emit_done(self) -> None:
        e = self._e
        done_text = self.scene.done_text.replace('"', "'")
        # Fade out everything still visible
        fade_targets = []
        if self._caption_var:
            fade_targets.append(self._caption_var)
        for eid in list(self._visible):
            if eid in self._group_var:
                fade_targets.append(self._group_var[eid])

        if fade_targets:
            e.emit(f"self.play({', '.join(f'FadeOut({v})' for v in fade_targets)}, run_time=0.5)")
            e.emit()

        e.emit(f"with self.voiceover(\"That completes the animation.\"):")
        e.indent()
        e.emit(f"done = Text(\"{done_text}\", font_size=40, color=SECONDARY, weight=BOLD)")
        e.emit("done.move_to(ORIGIN)")
        e.emit("self.play(GrowFromCenter(done))")
        e.dedent()
        e.emit("self.wait(2)")


def generate_manim_from_scene(scene: SceneGraph, plan: LayoutPlan) -> str:
    return ManimCodeGenerator(scene, plan).generate()
