"use client";

/**
 * The whole trip-planning conversation lives on this one page.
 *
 * Model: `turns` is an append-only transcript — every assistant prompt and
 * every user reply stays visible, which is what makes the context readable
 * as a conversation. Each assistant turn optionally carries a rich block
 * (`stage` + `data`), rendered by renderBlock() below.
 *
 * Interaction is dual-mode by design: the user can click a card OR type an
 * answer, and both funnel into the same POST. Clicks send a structured
 * `selection` the backend trusts verbatim; typed text goes through the
 * LLM parsers in backend/app/services/nlu.py. Once a turn has been
 * answered its block is frozen (`answered`), so old cards can't be
 * clicked a second time and re-send a stale choice.
 */
import { useEffect, useRef, useState } from "react";

import BudgetShort from "@/components/BudgetShort";
import ChatMessage from "@/components/ChatMessage";
import DestinationCards from "@/components/DestinationCards";
import FlightList from "@/components/FlightList";
import HotelList from "@/components/HotelList";
import IntakeForm from "@/components/IntakeForm";
import ItineraryCompare from "@/components/ItineraryCompare";
import TripSummary from "@/components/TripSummary";
import { sendMessage, startTrip } from "@/lib/api";
import { money } from "@/lib/money";
import type {
  IntakeSelection,
  PipelinePrompt,
  PipelineResponse,
  Selection,
  TripState,
} from "@/lib/types";

interface Turn {
  id: number;
  role: "assistant" | "user";
  text?: string;
  tone?: "error";
  prompt?: PipelinePrompt;
  trip?: TripState;
  answered?: boolean;
}

const GREETING =
  "Hi! Tell me about the trip you want — where you're thinking of going " +
  "(even vaguely), roughly when, and your budget. I'll figure out the rest.";

const EXAMPLES = [
  "A hill station somewhere in India, 5 days in October, budget ₹40000 for 2",
  "I want to see cherry blossoms in north east India, 4-5 days, ₹30000 for 2 people",
  "Beach trip from Mumbai, sometime in December, 1 week, ₹60000",
];

let idCounter = 0;
const nextId = () => ++idCounter;

/** The intake form carries far too much to echo field by field, so the
 *  user's bubble gets a one-line précis of what they just confirmed —
 *  enough to spot a mistake and correct it in the next message. */
function summariseIntake(v: IntakeSelection): string {
  const from = v.origins.map((o) => `${o.travellers} from ${o.city}`).join(", ");
  const bits = [
    v.destination_query,
    v.origins.length > 1 ? from : `${v.travellers} of us from ${v.origins[0]?.city}`,
    v.date_query ? `${v.date_query}${v.trip_days ? `, ${v.trip_days} days` : ""}` : null,
    v.budget_total ? `budget ${money(v.budget_total)}` : null,
    `split ${v.budget_split_pref.travel}/${v.budget_split_pref.hotel}/${v.budget_split_pref.activities}`,
  ];
  return bits.filter(Boolean).join(" · ");
}

export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([
    { id: nextId(), role: "assistant", text: GREETING },
  ]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  function applyResponse(res: PipelineResponse) {
    setThreadId(res.thread_id);
    if (res.status === "waiting_on_user") {
      setTurns((t) => [
        ...t,
        { id: nextId(), role: "assistant", text: res.prompt.text, prompt: res.prompt },
      ]);
    } else {
      setDone(true);
      setTurns((t) => [
        ...t,
        {
          id: nextId(),
          role: "assistant",
          text: "All set — here's your trip.",
          trip: res.trip,
        },
      ]);
    }
  }

  /** Single path for every reply, typed or clicked. `echo` is what shows in
   *  the user's bubble; `selection` is the structured form when clicked. */
  async function reply(echo: string, selection?: Selection) {
    if (busy || done) return;

    // Freeze the block being answered so its buttons can't fire again.
    setTurns((t) => [
      ...t.map((turn) => (turn.prompt ? { ...turn, answered: true } : turn)),
      { id: nextId(), role: "user", text: echo },
    ]);
    setBusy(true);

    try {
      const res = threadId
        ? await sendMessage(threadId, echo, selection)
        : await startTrip(echo);
      applyResponse(res);
    } catch (err) {
      setTurns((t) => [
        ...t,
        {
          id: nextId(),
          role: "assistant",
          tone: "error",
          text: (err as Error).message,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function submitTyped() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    reply(text);
  }

  function renderBlock(turn: Turn) {
    if (turn.trip) return <TripSummary trip={turn.trip} />;
    if (!turn.prompt) return null;

    const frozen = turn.answered || busy;
    const p = turn.prompt;

    switch (p.stage) {
      case "agent0_intake":
        return (
          <IntakeForm
            criteria={p.data.criteria}
            missing={p.data.missing}
            expected={p.data.expected}
            partyTypes={p.data.party_types}
            defaultSplit={p.data.default_split}
            disabled={frozen}
            onSubmit={(values) => reply(summariseIntake(values), values)}
          />
        );
      case "agent0_choose":
        return (
          <DestinationCards
            candidates={p.data.candidates}
            fixedWindows={p.data.date_mode === "fixed" ? p.data.date_windows : undefined}
            disabled={frozen}
            onConfirm={(names) =>
              reply(
                names.length > 1 ? `Compare ${names.join(" and ")}` : `Let's do ${names[0]}`,
                { destinations: names }
              )
            }
          />
        );
      case "agent3_choose":
        return (
          <ItineraryCompare
            itineraries={p.data.itineraries}
            dateWindow={p.data.date_window}
            availability={p.data.availability}
            bookable={p.data.bookable}
            disabled={frozen}
            onChoose={(d) => reply(`Go with ${d}`, { destination: d })}
          />
        );
      case "agent1_budget_short":
      case "agent2_budget_short": {
        const isFlights = p.stage === "agent1_budget_short";
        return (
          <BudgetShort
            allocated={p.data.allocated}
            cheapest={p.data.cheapest}
            suggested={p.data.suggested}
            disabled={frozen}
            onSubmit={(value) =>
              reply(
                `I can spend ${money(value)} on ${isFlights ? "flights" : "the stay"}`,
                isFlights ? { flights: value } : { hotel: value }
              )
            }
          />
        );
      }
      case "agent1_approve":
        return (
          <FlightList
            flights={p.data.flights}
            budget={p.data.budget}
            disabled={frozen}
            onSelect={(id) => {
              const f = p.data.flights.find((x) => x.id === id);
              reply(f ? `Book ${f.carrier} — ${money(f.price)}` : "Book that one", {
                option_id: id,
              });
            }}
          />
        );
      case "agent2_approve":
        return (
          <HotelList
            hotels={p.data.hotels}
            budget={p.data.budget}
            nights={p.data.nights}
            disabled={frozen}
            onSelect={(id) => {
              const h = p.data.hotels.find((x) => x.id === id);
              reply(h ? `Stay at ${h.name}` : "That one", { option_id: id });
            }}
          />
        );
      default:
        // agent1_origin has no rich block — it's answered by typing.
        return null;
    }
  }

  const showExamples = turns.length === 1 && !busy;

  return (
    <main className="mx-auto flex h-screen max-w-3xl flex-col px-4">
      <header className="flex items-center gap-2 py-4">
        <span className="grid h-8 w-8 place-items-center rounded-xl bg-[var(--accent)] text-sm text-[var(--accent-text)]">
          ✦
        </span>
        <div>
          <h1 className="text-sm font-semibold leading-tight">AI Assist for Travellers</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Plans and books your trip around your budget and dates
          </p>
        </div>
      </header>

      <div className="scroll-area flex-1 space-y-5 overflow-y-auto pb-6">
        {turns.map((turn) => (
          <ChatMessage key={turn.id} role={turn.role} text={turn.text} tone={turn.tone}>
            {renderBlock(turn)}
          </ChatMessage>
        ))}

        {showExamples && (
          <div className="animate-rise flex flex-wrap gap-2 pl-10">
            {EXAMPLES.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => reply(e)}
                className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-left text-xs text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
              >
                {e}
              </button>
            ))}
          </div>
        )}

        {busy && (
          <div className="flex gap-3 pl-10 text-[var(--text-muted)]">
            <span className="dot">●</span>
            <span className="dot" style={{ animationDelay: "0.2s" }}>
              ●
            </span>
            <span className="dot" style={{ animationDelay: "0.4s" }}>
              ●
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="sticky bottom-0 bg-transparent pb-4">
        <div className="flex items-end gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-[var(--shadow)]">
          <textarea
            rows={1}
            value={input}
            disabled={busy || done}
            placeholder={done ? "Trip planned — refresh to start over" : "Type your answer…"}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submitTyped();
              }
            }}
            className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-[var(--text-muted)] disabled:opacity-50"
          />
          <button
            type="button"
            onClick={submitTyped}
            disabled={busy || done || !input.trim()}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--accent)] text-[var(--accent-text)] transition-opacity disabled:opacity-30"
            aria-label="Send"
          >
            ↑
          </button>
        </div>
      </div>
    </main>
  );
}
