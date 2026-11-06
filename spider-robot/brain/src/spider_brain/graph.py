"""The LangGraph agent loop (same shape as desktop-agent/graph.py):

    call_model --(tool calls?)--> gate --(approved?)--> execute --> call_model
         |                         |
       (none)                  (rejected)
         v                         v
        END                    call_model

gate asks the owner (Supervisor) per the autonomy mode; execute runs the calls in order and
skips the rest of the batch after the first failure.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .calls import ToolCall, ToolOutcome
from .config import Settings
from .planner import Planner
from .policy import classify, describe, needs_approval
from .supervision.supervisor import Supervisor
from .tools import ToolExecutor

# Tools that only read; a batch made only of these runs in parallel (faster multi-tasking).
PARALLEL_SAFE = frozenset({"get_status", "scan_surroundings", "look"})


class AgentState(TypedDict):
    task: str
    pending: list[dict]
    step: int
    status: str
    last_text: str


def _calls(state: AgentState) -> list[ToolCall]:
    return [ToolCall(**c) for c in state["pending"]]


def build_graph(
    settings: Settings, planner: Planner, executor: ToolExecutor, supervisor: Supervisor
):
    bus = supervisor.bus

    async def call_model(state: AgentState) -> dict:
        await supervisor.gate_point()
        if state["step"] >= settings.max_steps:
            bus.publish("done", reason="max_steps", text="Reached the step limit.")
            return {"status": "done", "pending": [], "last_text": "Reached the step limit."}
        bus.publish("thinking", step=state["step"])
        plan = await planner.next_step()
        if plan.thinking:
            bus.publish("update", text=plan.thinking)
        if plan.text:
            bus.publish("message", text=plan.text)
        for call in plan.calls:
            bus.publish("proposed", description=describe(call),
                        risk=classify(call, settings).name.lower())
        if plan.done:
            bus.publish("done", reason=plan.stop_reason, text=plan.text)
            return {"status": "done", "pending": [], "last_text": plan.text}
        return {"status": "running", "pending": [asdict(c) for c in plan.calls],
                "last_text": plan.text}

    async def gate(state: AgentState) -> dict:
        await supervisor.gate_point()
        calls = _calls(state)
        for call in calls:
            risk = classify(call, settings)
            if needs_approval(risk, settings.autonomy):
                if settings.dashboard:
                    approved = await supervisor.request_approval(describe(call), risk.name.lower())
                    reason = "Rejected by the owner. Choose a different approach."
                else:  # nobody can approve without the dashboard: fail closed, never hang
                    approved = False
                    reason = (f"'{describe(call)}' needs owner approval ({risk.name}) but no "
                              "dashboard is open. Choose a lower-risk action.")
                if not approved:
                    if supervisor.aborted:
                        return {"status": "aborted", "pending": []}
                    planner.add_results([(c, ToolOutcome(reason, is_error=True)) for c in calls])
                    bus.publish("rejected", count=len(calls))
                    return {"status": "running", "pending": []}
        if supervisor.aborted:
            return {"status": "aborted", "pending": []}
        return {"status": "running"}

    async def run_one(call: ToolCall) -> ToolOutcome:
        bus.publish("acting", description=describe(call))
        out = await executor.run(call)
        bus.publish("result", description=describe(call), text=out.text[:500],
                    error=out.is_error)
        return out

    async def execute(state: AgentState) -> dict:
        calls = _calls(state)
        if len(calls) > 1 and all(c.name in PARALLEL_SAFE for c in calls):
            await supervisor.gate_point()
            outs = await asyncio.gather(*(run_one(c) for c in calls))
            planner.add_results(list(zip(calls, outs, strict=True)))
            return {"pending": [], "step": state["step"] + 1, "status": "running"}

        # Anything that moves runs strictly one at a time; stop the batch at the first error.
        results: list[tuple[ToolCall, ToolOutcome]] = []
        failed = False
        for call in calls:
            if failed or supervisor.aborted:
                results.append((call, ToolOutcome("Not executed: an earlier call failed.",
                                                  is_error=True)))
                continue
            await supervisor.gate_point()
            out = await run_one(call)
            results.append((call, out))
            failed = out.is_error
        planner.add_results(results)
        return {"pending": [], "step": state["step"] + 1, "status": "running"}

    def after_model(state: AgentState) -> str:
        return "gate" if state.get("pending") else END

    def after_gate(state: AgentState) -> str:
        if state.get("status") == "aborted":
            return END
        return "execute" if state.get("pending") else "call_model"

    graph = StateGraph(AgentState)
    graph.add_node("call_model", call_model)
    graph.add_node("gate", gate)
    graph.add_node("execute", execute)
    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", after_model, {"gate": "gate", END: END})
    graph.add_conditional_edges(
        "gate", after_gate, {"execute": "execute", "call_model": "call_model", END: END}
    )
    graph.add_edge("execute", "call_model")
    return graph.compile(checkpointer=MemorySaver())
