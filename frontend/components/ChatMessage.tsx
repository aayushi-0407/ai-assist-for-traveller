/**
 * One turn in the transcript. User turns are compact right-aligned
 * bubbles; assistant turns are left-aligned and can carry an arbitrary
 * rich block (destination cards, itinerary comparison, flight list...)
 * underneath their text, which is why they aren't constrained to a bubble
 * width the way user turns are.
 */
import type { ReactNode } from "react";

interface Props {
  role: "assistant" | "user";
  text?: string;
  tone?: "error";
  children?: ReactNode;
}

export default function ChatMessage({ role, text, tone, children }: Props) {
  if (role === "user") {
    return (
      <div className="animate-rise flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-text)]">
          {text}
        </div>
      </div>
    );
  }

  return (
    <div className="animate-rise flex gap-3">
      <div
        aria-hidden
        className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--accent)] text-xs text-[var(--accent-text)]"
      >
        ✦
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {text && (
          <div
            // whitespace-pre-line: when the assistant answers a question
            // mid-flow it returns "<answer>\n\n<the question again>", and
            // those breaks have to survive or the two run together.
            className={`inline-block max-w-[90%] whitespace-pre-line rounded-2xl rounded-tl-md px-4 py-2.5 text-sm ${
              tone === "error"
                ? "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300"
                : "bg-[var(--surface)] shadow-[var(--shadow)]"
            }`}
          >
            {text}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
