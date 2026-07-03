"""
Terminal tester for the chatbot brain.

This file is just the "terminal face" — it handles typing and printing. All the
actual thinking lives in brain.py, which the web server will also use. Keeping
them separate is the whole point of Step 1: one brain, many faces.

Run it:   python chatbot.py
"""

import brain
from companies import COMPANIES, knowledge_path

COMPANY_ID = "coverfirst"           # which company to test (see companies.py)
COMPANY_NAME = COMPANIES[COMPANY_ID]
MAX_HISTORY_MESSAGES = 10   # only keep the last few turns (keeps cost down)


def main():
    knowledge = brain.load_knowledge(knowledge_path(COMPANY_ID))
    messages = []           # the conversation so far

    print(f"\n{COMPANY_NAME} assistant is ready. Ask a question (or type 'quit').\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"quit", "exit"}:
            break

        messages.append({"role": "user", "content": question})

        # Ask the brain for an answer (this is the one line that does the work).
        reply, usage = brain.answer(COMPANY_NAME, knowledge, messages)
        print(f"Bot: {reply}")

        # Show what that message cost, so you can watch your spend.
        cost = brain.cost_usd(usage)
        print(
            f"  [in {usage.input_tokens} + {usage.cache_read_input_tokens} cached, "
            f"out {usage.output_tokens} tokens · ~${cost:.5f}]\n"
        )

        # Save the reply, then trim history so old turns don't inflate cost.
        messages.append({"role": "assistant", "content": reply})
        messages = messages[-MAX_HISTORY_MESSAGES:]


if __name__ == "__main__":
    main()
