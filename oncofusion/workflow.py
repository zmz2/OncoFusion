"""Equivalent native and real LangGraph execution of one explicit research graph.

Nodes deliberately execute serially so budget accounting and traces stay deterministic.
A graph backend change is infrastructure, not evidence of better biomedical reasoning.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Callable, TypedDict

from .schemas import ROLES, RunConfig


class WorkflowState(TypedDict):
    completed: list[str]


def dependency_identity(config: RunConfig) -> dict[str, str]:
    if config.workflow_backend == "native":
        return {}
    try:
        return {name: version(name) for name in ("langgraph", "langchain-core", "langgraph-checkpoint")}
    except PackageNotFoundError as exc:
        raise RuntimeError("langgraph backend requires pip install -e '.[graph]'") from exc


def role_order(config: RunConfig) -> tuple[str, ...]:
    if config.mode == "fixed_five":
        roles = ("genomics", "pathology", "drug", "literature")
    else:
        roles = ROLES[:-1]
    if config.evidence_first:
        roles = ("literature",) + tuple(r for r in roles if r != "literature")
    return roles


def specification(config: RunConfig) -> dict:
    nodes = list(role_order(config)) if config.mode in ("multi", "fixed_five") else ["single_analysis"]
    nodes += ["requery", "decision"]
    return {"backend": config.workflow_backend, "evidence_first": config.evidence_first,
            "nodes": nodes, "initial_sequence": nodes[:-2], "terminal": "decision",
            "conditional": {"after_analysis": ["requery", "decision"], "after_requery": "decision"},
            "max_requeries": int(config.ablations.targeted_requery and config.mode == "multi"), "parallel": False, "checkpoint_resume": False}


def execute(config: RunConfig, analyze: Callable[[str], None], single: Callable[[], None],
            needs_requery: Callable[[], bool], requery: Callable[[], None],
            decide: Callable[[], None]) -> None:
    roles = role_order(config) if config.mode in ("multi", "fixed_five") else ("single_analysis",)
    actions = {role: (lambda r=role: analyze(r)) for role in roles}
    if roles == ("single_analysis",):
        actions = {"single_analysis": single}
    if config.workflow_backend == "native":
        for action in actions.values():
            action()
        if needs_requery():
            requery()
        decide()
        return

    dependency_identity(config)
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(WorkflowState)

    def node(name, action):
        def invoke(state):
            action()
            return {"completed": state["completed"] + [name]}
        return invoke

    for name, action in {**actions, "requery": requery, "decision": decide}.items():
        graph.add_node(name, node(name, action))
    graph.add_edge(START, roles[0])
    for first, second in zip(roles, roles[1:]):
        graph.add_edge(first, second)
    graph.add_conditional_edges(roles[-1], lambda state: "requery" if needs_requery() else "decision",
                                {"requery": "requery", "decision": "decision"})
    graph.add_edge("requery", "decision")
    graph.add_edge("decision", END)
    graph.compile().invoke({"completed": []}, config={"recursion_limit": 20})
