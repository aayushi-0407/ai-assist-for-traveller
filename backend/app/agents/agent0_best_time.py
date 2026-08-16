"""
Agent 0 — Where to go, and when (PRD section 7)

Split into three graph nodes:

  intake   : [interrupt] fills the four planning criteria — destination
             description, source(s), travel window, budget and how it
             splits. Prefilled from the opening message, so in the normal
             case the user is confirming rather than answering.
  research : produces candidate destinations, each with a reason and the
             best window to visit, informed by everything intake gathered.
             No pause.
  choose   : [interrupt] shows those candidates and lets the user shortlist
             the one(s) they want itineraries built for, plus any date
             preference. Free text ("Shillong and Gangtok, first week of
             Nov") or a click both work — see services/nlu.py.

Why intake runs BEFORE research: party size, departure city and budget all
change which destinations are worth suggesting at all. Asking afterwards
means researching against assumptions and then throwing the answers away.
The criteria logic itself lives in services/intake.py; this file only owns
the conversation around it.

The shortlist then flows to Agent 3, which builds a full itinerary per
shortlisted destination so the user can compare before locking one in.
Agent 0 deliberately does NOT resolve a single destination — that decision
belongs to Agent 3's compare step.

Why separate nodes: LangGraph replays a node's code from the top on every
resume from interrupt(). `research` is a chain of real LLM + Places calls,
so it must be persisted as its own node's return *before* `choose` pauses
— otherwise every resume would re-run the research and could hand back a
different candidate list than the one the user was actually looking at.
Same reasoning as agent1_flights.py; see its docstring.
"""
from datetime import date
from typing import Any, Dict

from langgraph.types import interrupt

from app.agents import offscript
from app.services import budget as budget_service
from app.services import intake, nlu, reviews


def _days_between(start: str, end: str) -> int:
    return max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days)


def extract(state: Dict) -> Dict:
    """Read whatever the four criteria the opening message already answers.

    Its own node purely for replay safety: this is a live LLM call, and if
    it sat inside `collect` it would re-run on every resume and could hand
    the merge step a different prefill than the one the user was looking
    at when they replied. Checkpointing it first pins it. Same rule as
    research/choose below — see the module docstring.
    """
    extracted = nlu.parse_opening_message(state["opening_message"])
    criteria = intake.merge(intake.blank(), intake.sanitise(extracted))

    # Deliberately no fallback to the raw opening message here. If the
    # extractor found nothing about *where*, the message was something like
    # "plan me something" — using it as the destination brief would send
    # that string to research as if it meant anything. Leaving it null lets
    # the intake loop ask, which is the PRD's "too bare to research at all"
    # case (section 7).
    return {"intake_criteria": criteria}


def _intake_question(gaps: Dict[str, list], asked_before: bool) -> str:
    """The question for this round.

    Sole owner of the "what's still outstanding" phrasing — the loop must
    not also prepend its own version, or a re-ask says the same thing
    twice. `asked_before` is what makes a repeat acknowledge itself instead
    of looking like the reply was ignored.
    """
    outstanding = gaps["required"] + gaps["expected"]

    if not outstanding:
        return (
            "Here's what I've got. Check it over — especially how you'd like "
            "the budget divided up, since that tells me whether to look for "
            "somewhere to unwind or somewhere with plenty to do."
        )

    if asked_before:
        # The "I'll assume something" offer is only honest when everything
        # left is an EXPECTED field. There is no default for a REQUIRED one,
        # so promising to move on without it would be a lie the next round
        # immediately contradicts.
        if gaps["required"]:
            return (
                f"I can't start without {intake.describe(gaps['required'])} — "
                "there's no sensible default for that one, so I do need it "
                "from you."
            )
        return (
            f"I still need {intake.describe(outstanding)} — or say you're not "
            "sure and I'll make a sensible assumption and get going."
        )

    if gaps["required"]:
        helpful = (
            f", and it'd help to know {intake.describe(gaps['expected'])}"
            if gaps["expected"]
            else ""
        )
        return (
            f"Before I go looking I need {intake.describe(gaps['required'])}"
            f"{helpful}. Change anything else I've got wrong while you're there."
        )

    return f"Nearly there — just {intake.describe(outstanding)} and I can start looking."


def collect(state: Dict) -> Dict:
    """[interrupt] Hold here until Agent 0's four criteria are all answered.

    Prefilled from `extract`, so the common case is a confirmation rather
    than an interrogation (PRD section 7: "research, don't interrogate").

    --------------------------------------------------------------------
    LOOP CONTRACT — three ways out, in priority order:

      1. Everything answered              -> normal exit.
      2. Only EXPECTED fields left, and
         MAX_STALLED_ROUNDS replies in a
         row filled nothing new           -> concede those, apply their
                                             defaults, say so, exit.
      3. A REQUIRED field is still empty  -> no exit. There is no default
                                             for these, so continuing would
                                             mean researching against a
                                             blank.

    Case 2 is what stops "keep asking until it's complete" from becoming a
    hung node when the user genuinely doesn't know how many days they have.
    Progress — not reply count — is the trigger, so a user who is answering
    is never cut off mid-conversation, however many rounds it takes.

    REPLAY NOTE: `stalled` and `conceded` are locals inside a node that
    interrupts, so LangGraph rebuilds them by replaying every prior reply
    from the top on each resume. That reconstruction is exact as long as
    the parsers are deterministic — the same temperature-0 assumption the
    rest of the pipeline already rests on.
    --------------------------------------------------------------------
    """
    criteria = state["intake_criteria"]
    note = None
    stalled = 0
    rounds = 0
    conceded: list = []

    while True:
        gaps = intake.outstanding(criteria, concede=bool(conceded))
        question = _intake_question(gaps, asked_before=rounds > 0)
        rounds += 1

        reply = interrupt({
            "stage": "agent0_intake",
            "text": f"{note}\n\n{question}" if note else question,
            "data": {
                "criteria": criteria,
                "missing": gaps["required"],
                "expected": gaps["expected"],
                "party_types": list(intake.PARTY_TYPES),
                "default_split": budget_service.DEFAULT_PREFERENCE,
            },
        })

        kind, payload = offscript.triage(reply, state, question)
        if kind == "note":
            # A question rather than an answer. Not progress, but not
            # stalling either — they're still engaged, so don't count it.
            note = payload
            continue
        if kind == "restart":
            # No destinations have been proposed yet, so there is nothing to
            # restart *from* — a reply that states where they want to go is
            # simply the destination criterion being answered.
            criteria = intake.merge(
                criteria, {"destination_query": payload["restart_query"]}
            )

        before = intake.filled(criteria)
        update = nlu.parse_intake_reply(
            reply.get("message", ""), criteria, reply.get("selection")
        )
        criteria = intake.merge(criteria, intake.sanitise(update))
        stalled = 0 if intake.filled(criteria) != before else stalled + 1

        gaps = intake.outstanding(criteria, concede=bool(conceded))
        if intake.complete(gaps):
            break

        if gaps["expected"] and stalled >= intake.MAX_STALLED_ROUNDS:
            conceded = gaps["expected"]
            if intake.complete(intake.outstanding(criteria, concede=True)):
                break

        # No note here — _intake_question already states what's outstanding,
        # and saying it twice reads as the assistant talking past itself.
        note = None

    updates: Dict[str, Any] = {
        **intake.derive(criteria),
        "intake_criteria": criteria,
        # Carried forward so the next question can own up to them. An
        # assumption the user never sees is one they can't correct.
        "intake_assumptions": conceded,
    }
    updates.update(_resolve_windows(criteria, updates))

    # The node's own contract, not the user's. Anything caught here is a
    # derive() bug — failing loudly beats handing Agent 3 a half-built trip.
    incomplete = intake.validate(updates)
    if incomplete:
        raise ValueError(f"Agent 0 intake finished without: {', '.join(incomplete)}")

    return updates


def _resolve_windows(criteria: Dict[str, Any], derived: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the travel-window criterion into concrete dates, if it can be.

    Fixed dates get pinned here and now. A flexible month deliberately does
    NOT — the best week inside March is different for Shillong than for
    Goa, so that call belongs to research, which then hands each candidate
    its own window. All we carry forward is the constraint and the length.

    `trip_days` always comes back set, since it's part of what Agent 0
    contracts to hand on (intake.CONTRACT): a fixed window supplies it, a
    flexible one falls back to intake.FALLBACK_TRIP_DAYS.
    """
    trip_days = criteria.get("trip_days")
    unpinned = {"date_windows": [], "trip_days": trip_days or intake.FALLBACK_TRIP_DAYS}

    if derived["date_mode"] != "fixed" or not derived["date_query"]:
        return unpinned

    windows = nlu.parse_date_windows(derived["date_query"], trip_days)
    if not windows:
        return unpinned

    first = windows[0]
    return {
        "date_windows": windows,
        "selected_date_window": {"start": first["start"], "end": first["end"]},
        "trip_days": trip_days or _days_between(first["start"], first["end"]),
    }


def research(state: Dict) -> Dict:
    """Research where and when to go, against the criteria intake gathered.

    Runs again from the start if the user changed their mind mid-flow —
    `restart_query` holds the new requirement and replaces the destination
    brief. Everything else they've already told us (budget, party, origin,
    dates) still stands, and is what `intake.summarise` carries into the
    prompt so a re-search doesn't drift off-budget or out of region.
    """
    destination_query = (
        state.get("restart_query")
        or state.get("destination_query")
        or state["opening_message"]
    )

    candidates = reviews.research_destinations(
        destination_query,
        state.get("date_query") or "",
        context=intake.summarise(state),
        trip_days=state.get("trip_days"),
        fixed_windows=state.get("date_windows") or [],
    )

    return {
        "destination_query": destination_query,
        "candidate_destinations": candidates,
        # Consume the restart signal, or the conditional edges would loop
        # straight back here forever.
        "restart_query": None,
    }


def _window_for(candidate: Dict[str, Any]) -> Dict[str, str]:
    return {"start": candidate["start"], "end": candidate["end"]}


def _choose_question(state: Dict) -> str:
    # Any default the intake loop had to fall back on gets said out loud
    # here, at the first moment the user can see what it produced.
    assumed = state.get("intake_assumptions") or []
    prefix = (
        f"You weren't sure on a few things, so I {intake.describe_concessions(assumed)} "
        "— say the word if you'd rather change any of that. "
        if assumed
        else ""
    )
    base = (
        f"{prefix}Here's what I found. Which of these would you like me to "
        "build an itinerary for? Pick one, or a few to compare"
    )
    # Dates are only still open if the user gave a flexible window at
    # intake; with fixed dates already pinned, asking again invites them to
    # contradict what they just told us.
    windows = state.get("date_windows") or []
    if state.get("date_mode") == "fixed" and windows:
        if len(windows) > 1:
            slots = " or ".join(w.get("label") or w["start"] for w in windows)
            return f"{base}. I've got you down for {slots} — say which slot you'd rather use."
        return f"{base}."
    return f"{base} — and tell me your dates if you have them in mind."


def choose(state: Dict) -> Dict:
    """Let the user shortlist destinations to compare, and set the dates."""
    candidates = state["candidate_destinations"]
    question = _choose_question(state)
    note = None

    while True:
        reply = interrupt({
            "stage": "agent0_choose",
            "text": f"{note}\n\n{question}" if note else question,
            "data": {
                "candidates": candidates,
                # Fixed slots the user already committed to at intake, so
                # the cards can show them instead of each candidate's own
                # researched window.
                "date_windows": state.get("date_windows") or [],
                "date_mode": state.get("date_mode") or "flexible",
            },
        })
        # Reply shape from main.py: {"message": "...", "selection": {...}|None}
        kind, payload = offscript.triage(reply, state, question)
        if kind == "restart":
            return payload
        if kind == "note":
            note = payload
            continue

        parsed = nlu.parse_destination_choice(
            reply.get("message", ""), candidates, reply.get("selection")
        )
        if parsed["destinations"]:
            break
        note = None
        # Couldn't tell what they meant — ask again rather than guessing a
        # destination for them. interrupt() inside a loop is safe: LangGraph
        # replays already-answered interrupts from the checkpoint and only
        # pauses on the new one.

    shortlisted = parsed["destinations"]
    chosen_candidates = [c for c in candidates if c["name"] in shortlisted]

    # Dates, in priority order:
    #   1. whatever they just said — the most recent word always wins;
    #   2. a fixed slot they committed to at intake;
    #   3. the window research picked for the first shortlisted place, which
    #      is the seasonally best one inside their flexible month.
    if parsed.get("date_query"):
        window = nlu.parse_date_window(parsed["date_query"], state.get("trip_days"))
    elif state.get("date_mode") == "fixed" and state.get("selected_date_window"):
        window = state["selected_date_window"]
    else:
        window = _window_for(chosen_candidates[0])

    start, end = window["start"], window["end"]

    return {
        "shortlisted_destinations": shortlisted,
        "selected_date_window": {"start": start, "end": end},
        "trip_days": _days_between(start, end),
    }
