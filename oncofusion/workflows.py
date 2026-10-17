"""Real LangGraph node orchestration plus a deterministic parity reference.

Source: LangGraph workflows-agents guide. No checkpoint deserialization or remote tracing.
The engine owns model/tool budgets, source isolation and persistent API events.
"""
from collections.abc import Callable
from typing import TypedDict

EVIDENCE_FIRST_ROLES = ("literature", "timeline", "genomics", "pathology", "drug", "verifier")


class WorkflowState(TypedDict):
    visited: list[str]
    requery: bool


def evidence_first_workflow(execute: Callable[[str], None], needs_requery: Callable[[], bool],
                            requery: Callable[[], None], orchestrator: str) -> None:
    if orchestrator == "python":
        for role in EVIDENCE_FIRST_ROLES:
            execute(role)
        if needs_requery():
            requery()
        execute("decision")
        return
    from langgraph.graph import END, START, StateGraph
    graph = StateGraph(WorkflowState)

    def node(role):
        def invoke(state):
            execute(role)
            return {"visited": state["visited"] + [role]}
        return invoke

    for role in (*EVIDENCE_FIRST_ROLES, "decision"):
        graph.add_node(role, node(role))

    def recall(state):
        requery()
        return {"visited": state["visited"] + ["targeted_requery"], "requery": True}

    graph.add_node("targeted_requery", recall)
    graph.add_edge(START, "literature")
    for left, right in zip(EVIDENCE_FIRST_ROLES, EVIDENCE_FIRST_ROLES[1:]):
        graph.add_edge(left, right)
    graph.add_conditional_edges("verifier", lambda state: "requery" if needs_requery() else "done",
                               {"requery": "targeted_requery", "done": "decision"})
    graph.add_edge("targeted_requery", "decision")
    graph.add_edge("decision", END)
    # No checkpointer, LangSmith client, runnable LLM or remote tool is created here.
    graph.compile().invoke({"visited": [], "requery": False}, config={"recursion_limit": 12})
