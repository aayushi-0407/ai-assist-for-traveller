"""
Orchestrator — wires the agents into one sequential LangGraph pipeline.
This is the single file that defines pipeline ORDER; agent logic itself
lives in app/agents/*.py.

Graph shape — note itinerary comes BEFORE booking:

    START
      -> agent0_extract           read the criteria out of the opening message
      -> agent0_intake            [pause] confirm/fill destination, source(s),
                                  travel window, budget + how it splits
      -> agent0_research          find candidate destinations + best windows
      -> agent0_choose            [pause] user shortlists places to compare
      -> agent1_ask_origin        [pause] fallback only; intake already has it

           ══ PARALLEL ══ both branches run on the whole shortlist
      ├─> agent3_build            one itinerary per shortlisted place
      └─> availability            Agents 1+2: flights AND hotels, on a
                                  window they agree is bookable
           ══ join ══

      -> agent3_choose            [pause] user compares itinerary + real
                                  price + real dates, locks the destination
      -> agent4_routing           optimise the winning itinerary's routes
      -> availability_carry       pull the winner's pre-searched options
      -> agent1_approve_and_book  [pause] user picks, agent books
      -> agent2_approve           [pause] user picks, gets booking link
      -> END

Why the fan-out: nothing Agent 3 needs depends on Agents 1/2, and nothing
they need depends on Agent 3 — all three want the same shortlist and
nothing else. Running them in sequence just made the user wait through
three round trips to learn something they could have been told at once.

Why searching all destinations is safe but booking isn't: search is cheap
and reversible, so doing it for every shortlisted place up front means the
comparison shows real prices and real dates. Booking is neither, so it
stays after the user locks a destination (PRD section 8) — the parallel
branch only ever *searches*.

Why itinerary still comes before booking: the user decides *which*
destination by comparing real day-by-day plans, so nothing can be booked
until that comparison happens.

Agent 1's separate `search` node and the `ask_budget` pause are both gone.
Search moved into the parallel `availability` branch; the budget split is
now collected by Agent 0's intake form (criterion 4), so asking again here
was making the user answer the same question twice.

Each node is a plain `fn(state) -> partial_state_dict`. LangGraph merges
the returned dict into the shared TripState (app/state.py) before calling
the next node.

Every agent that shows the user options is split into a "produce" node and
a separate "[pause]" node. That's a correctness requirement, not a style
choice — LangGraph replays a node from the top on resume, so anything
non-deterministic (an LLM call, a live flight search) has to be
checkpointed before the pause, or a resume could show one thing and act on
another. See agent1_flights.py's docstring for the full explanation, and
follow the same pattern for any new stage.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents import (
    agent0_best_time,
    agent1_flights,
    agent2_hotels,
    agent3_itinerary,
    agent4_routing,
    availability,
    offscript,
)
from app.state import TripState

# The two branches that run at once on the shortlist. Named here because
# the fan-out edge and the restart edge both have to agree on the list.
PARALLEL_BRANCHES = ["agent3_build", "availability"]


def build_graph():
    graph = StateGraph(TripState)

    graph.add_node("agent0_extract", agent0_best_time.extract)
    graph.add_node("agent0_intake", agent0_best_time.collect)
    graph.add_node("agent0_research", agent0_best_time.research)
    graph.add_node("agent0_choose", agent0_best_time.choose)
    graph.add_node("agent1_ask_origin", agent1_flights.ask_origin)
    graph.add_node("agent3_build", agent3_itinerary.build)
    graph.add_node("availability", availability.search_all)
    graph.add_node("agent3_choose", agent3_itinerary.choose)
    graph.add_node("agent4_routing", agent4_routing.run)
    graph.add_node("availability_carry", availability.carry_forward)
    graph.add_node("agent1_raise_budget", agent1_flights.raise_budget)
    graph.add_node("agent1_approve_and_book", agent1_flights.approve_and_book)
    graph.add_node("agent2_raise_budget", agent2_hotels.raise_budget)
    graph.add_node("agent2_approve", agent2_hotels.approve)

    graph.add_edge(START, "agent0_extract")
    graph.add_edge("agent0_extract", "agent0_intake")
    graph.add_edge("agent0_intake", "agent0_research")
    graph.add_edge("agent0_research", "agent0_choose")

    # The fan-out. Returning a LIST of node names from the path function is
    # what schedules both into the SAME superstep — that's what makes them
    # concurrent rather than merely adjacent. (A path_map dict can't express
    # this: its values are single node names.) The two branches write
    # disjoint state keys — itinerary_options vs availability — so no
    # channel reducer is needed to merge their returns.
    def fan_out(state):
        if state.get("restart_query"):
            return "agent0_research"
        return PARALLEL_BRANCHES

    graph.add_conditional_edges(
        "agent1_ask_origin", fan_out, ["agent0_research"] + PARALLEL_BRANCHES
    )
    # agent3_choose has both branches as inbound edges, so LangGraph waits
    # for BOTH before running it. Comparison needs the itinerary and the
    # price together; showing one without the other is the sequencing we
    # just removed.
    for branch in PARALLEL_BRANCHES:
        graph.add_edge(branch, "agent3_choose")

    graph.add_edge("agent4_routing", "availability_carry")

    # Any stage that takes a free-text reply can be told "actually, I want
    # to go somewhere else entirely" (see agents/offscript.py). That sets
    # `restart_query`, and these edges send the flow back to Agent 0 to
    # research the new requirement instead of continuing with stale picks.
    for source, following in [
        ("agent0_choose", "agent1_ask_origin"),
        ("agent3_choose", "agent4_routing"),
    ]:
        graph.add_conditional_edges(
            source,
            offscript.is_restarting,
            {"research": "agent0_research", "next": following},
        )

    # If nothing came back within budget, divert to a node that asks the
    # user to raise it, then loop back — rather than dead-ending or showing
    # options they can't afford. The loop returns to `availability_carry`,
    # not to a fresh search: re-searching would hand back new offer IDs at
    # new prices, so it re-filters the options the user was already shown.
    graph.add_conditional_edges(
        "availability_carry",
        agent1_flights.needs_more_budget,
        {"raise_budget": "agent1_raise_budget", "approve": "agent1_approve_and_book"},
    )
    graph.add_edge("agent1_raise_budget", "availability_carry")

    # Booking can end in a change of mind ("actually, somewhere else") as
    # well as an unaffordable hotel, so this edge has to consider both —
    # a bare needs_more_budget would swallow the restart signal.
    def after_booking(state) -> str:
        if state.get("restart_query"):
            return "research"
        return agent2_hotels.needs_more_budget(state)

    graph.add_conditional_edges(
        "agent1_approve_and_book",
        after_booking,
        {
            "research": "agent0_research",
            "raise_budget": "agent2_raise_budget",
            "approve": "agent2_approve",
        },
    )
    graph.add_edge("agent2_raise_budget", "agent2_approve")

    graph.add_conditional_edges(
        "agent2_approve",
        offscript.is_restarting,
        {"research": "agent0_research", "next": END},
    )

    # MemorySaver = in-process checkpointer, required for interrupt()/resume
    # to work and for each trip's progress to persist between API calls.
    # It's wiped on process restart — swap for a Postgres/Redis checkpointer
    # (see PRD Non-Functional Requirements) before this goes to production.
    return graph.compile(checkpointer=MemorySaver())
