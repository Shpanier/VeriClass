"""CrewAI agent layer (Gemini-only).

Replaces the old one-shot, stateless LLM calls with memory-backed CrewAI agents:

  tutor   — drafts the teacher-reviewable answer variants (nudge/normal/more,
            EN+HE), grounded in the student's actual conversation.
  probe   — drafts targeted comprehension questions ("Ask Them"), grounded in
            the conversation and explicitly told NOT to repeat prior probes.
  grader  — scores a student's probe answer.

All three reach Gemini through `agents.llm.gemini_llm()`. Conversation "memory"
is explicit context threading from the SQLite `messages`/`probes` tables (see
`agents.memory`) — deterministic, Gemini-only, no embeddings store.
"""
