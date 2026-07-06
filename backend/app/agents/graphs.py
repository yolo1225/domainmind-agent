from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    decide_next_step,
    generate_resource,
    load_profile,
    persist_resource,
    retrieve_knowledge,
    review_resource,
    route_after_decision,
)
from app.agents.state import AgentGraphState


def build_generation_graph():
    graph = StateGraph(AgentGraphState)
    graph.add_node("load_profile", load_profile)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("generate_resource", generate_resource)
    graph.add_node("review_resource", review_resource)
    graph.add_node("decide_next_step", decide_next_step)
    graph.add_node("persist_resource", persist_resource)

    graph.add_edge(START, "load_profile")
    graph.add_edge("load_profile", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "generate_resource")
    graph.add_edge("generate_resource", "review_resource")
    graph.add_edge("review_resource", "decide_next_step")
    graph.add_conditional_edges(
        "decide_next_step",
        route_after_decision,
        {
            "persist_resource": "persist_resource",
            "retrieve_knowledge": "retrieve_knowledge",
            "end": END,
        },
    )
    graph.add_edge("persist_resource", END)
    return graph.compile()
