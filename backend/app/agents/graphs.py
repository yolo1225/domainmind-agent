from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.legacy_state import AgentGraphState

NodeFunc = Callable[[AgentGraphState], AgentGraphState]


def build_learning_graph(
    node_overrides: dict[str, NodeFunc] | None = None,
    checkpointer: Any | None = None,
):
    """Build the single top-level graph used by initial and feedback tasks."""

    overrides = node_overrides or {}
    node_map: dict[str, NodeFunc] = {
        "prepare_task": nodes.prepare_task,
        "interpret_feedback": nodes.interpret_feedback,
        "analyze_profile": nodes.analyze_profile,
        "retrieve_knowledge": nodes.retrieve_knowledge,
        "generate_resource": nodes.generate_resource,
        "review_resource": nodes.review_resource,
        "human_review": nodes.human_review,
        "finalize_task": nodes.finalize_task,
    }
    node_map.update(overrides)

    graph = StateGraph(AgentGraphState)
    for name, func in node_map.items():
        graph.add_node(name, func)

    graph.add_edge(START, "prepare_task")
    graph.add_conditional_edges(
        "prepare_task",
        nodes.route_after_prepare,
        {
            "interpret_feedback": "interpret_feedback",
            "analyze_profile": "analyze_profile",
            "human_review": "human_review",
        },
    )
    graph.add_edge("interpret_feedback", "analyze_profile")
    graph.add_conditional_edges(
        "analyze_profile",
        nodes.route_after_profile,
        {"retrieve_knowledge": "retrieve_knowledge", "finalize_task": "finalize_task"},
    )
    graph.add_edge("retrieve_knowledge", "generate_resource")
    graph.add_edge("generate_resource", "review_resource")
    graph.add_edge("review_resource", "finalize_task")
    graph.add_conditional_edges(
        "finalize_task",
        nodes.route_after_finalize,
        {"retrieve_knowledge": "retrieve_knowledge", "human_review": "human_review", "end": END},
    )
    graph.add_conditional_edges(
        "human_review",
        nodes.route_after_human_review,
        {"retrieve_knowledge": "retrieve_knowledge", "finalize_task": "finalize_task", "end": END},
    )
    return graph.compile(checkpointer=checkpointer)
