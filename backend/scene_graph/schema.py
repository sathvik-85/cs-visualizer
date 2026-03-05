from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field


# ── Element models ─────────────────────────────────────────────────────────────

class ArrayElement(BaseModel):
    type: Literal["array"] = "array"
    id: str
    values: list[int | str]
    label: str = ""


class BSTNode(BaseModel):
    id: str | int
    value: int | str
    left: Optional[BSTNode] = None
    right: Optional[BSTNode] = None

BSTNode.model_rebuild()


class BSTElement(BaseModel):
    type: Literal["bst"] = "bst"
    id: str
    root: BSTNode


class GraphEdge(BaseModel):
    from_node: str | int
    to_node: str | int
    directed: bool = False
    weight: Optional[str] = None


class GraphElement(BaseModel):
    type: Literal["graph"] = "graph"
    id: str
    nodes: list[str | int]
    edges: list[GraphEdge]
    layout: Literal["circular"] = "circular"


class DPTableElement(BaseModel):
    type: Literal["dp_table"] = "dp_table"
    id: str
    rows: int
    cols: int
    row_labels: list[str] = []
    col_labels: list[str] = []
    initial_values: list[list[str]] = []


class StackElement(BaseModel):
    type: Literal["stack"] = "stack"
    id: str
    values: list[int | str]
    label: str = "Stack"


class QueueElement(BaseModel):
    type: Literal["queue"] = "queue"
    id: str
    values: list[int | str]
    label: str = "Queue"


class TextBlock(BaseModel):
    type: Literal["text_block"] = "text_block"
    id: str
    lines: list[str]
    font_size: int = 22


AnyElement = Annotated[
    Union[
        ArrayElement, BSTElement, GraphElement,
        DPTableElement, StackElement, QueueElement, TextBlock,
    ],
    Field(discriminator="type"),
]


# ── Action models ──────────────────────────────────────────────────────────────

class HighlightAction(BaseModel):
    action: Literal["highlight"] = "highlight"
    target_id: str
    indices: list[int] = []          # array indices; empty = whole element
    color: str = "HIGHLIGHT"         # palette key


class SwapAction(BaseModel):
    action: Literal["swap"] = "swap"
    target_id: str
    index_a: int
    index_b: int


class CompareAction(BaseModel):
    action: Literal["compare"] = "compare"
    target_id: str
    indices: list[int]


class MarkVisitedAction(BaseModel):
    action: Literal["mark_visited"] = "mark_visited"
    target_id: str
    node_ids: list[str | int]


class SetValueAction(BaseModel):
    action: Literal["set_value"] = "set_value"
    target_id: str
    row: int
    col: int
    value: str


class PushAction(BaseModel):
    action: Literal["push"] = "push"
    target_id: str
    value: int | str


class PopAction(BaseModel):
    action: Literal["pop"] = "pop"
    target_id: str


class FadeOutAction(BaseModel):
    action: Literal["fade_out"] = "fade_out"
    target_id: str


AnyAction = Annotated[
    Union[
        HighlightAction, SwapAction, CompareAction, MarkVisitedAction,
        SetValueAction, PushAction, PopAction, FadeOutAction,
    ],
    Field(discriminator="action"),
]


# ── Step ──────────────────────────────────────────────────────────────────────

class Step(BaseModel):
    step_id: int
    voiceover: str
    caption: str
    introduce_elements: list[str] = []
    actions: list[AnyAction] = []
    remove_elements: list[str] = []


# ── SceneGraph ────────────────────────────────────────────────────────────────

class SceneGraph(BaseModel):
    title: str
    topic: str
    elements: dict[str, AnyElement]
    steps: list[Step]
    done_text: str = "Done!"
