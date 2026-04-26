from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from crew_agent.agents import get_agent_definition
from crew_agent.conversation.router import classify_request
from crew_agent.core.models import AppConfig, ExecutionPlan, Host
from crew_agent.handlers.code import build_code_plan
from crew_agent.handlers.deterministic import build_builtin_plan
from crew_agent.handlers.planner import create_execution_plan
from crew_agent.handlers.workspace import build_workspace_plan


@dataclass(frozen=True)
class TaskSpecialist:
    name: str
    build_plan: Callable[[str, list[Host]], ExecutionPlan | None]


SPECIALISTS: tuple[TaskSpecialist, ...] = (
    TaskSpecialist(name="deterministic", build_plan=build_builtin_plan),
    TaskSpecialist(name="workspace", build_plan=build_workspace_plan),
    TaskSpecialist(name="code", build_plan=build_code_plan),
)


from crew_agent.core.memory import (
    is_identity_question,
    is_user_identity_question,
    is_greeting,
    load_workspace_memory,
)

def resolve_execution_plan(
    request: str,
    hosts: list[Host],
    config: AppConfig,
    thread: ConversationThread | None = None,
) -> tuple[ExecutionPlan, str]:
    """
    Decisive Routing: Identity/Chat -> Specialists -> LLM.
    """
    lowered = request.lower().strip()
    
    # 0. Fast Identity & Chat Checks
    if is_identity_question(lowered) or is_user_identity_question(lowered) or is_greeting(lowered):
        memory = load_workspace_memory()
        if is_greeting(lowered):
            msg = f"Hello! I am {memory.assistant_name}. How can I assist you today?"
        elif is_identity_question(lowered):
            msg = f"My name here is {memory.assistant_name}."
        else:
            msg = f"Your name here is {memory.user_name or 'unknown'}."
            
        return ExecutionPlan(summary=msg, steps=[], target_hosts=[], raw={"chat": True}), "identity"

    # 1. Try high-precision local specialists
    for specialist in SPECIALISTS:
        # We'll update the Specialist Callable signature in a follow-up if needed, 
        # but for now we pass it only if they accept it.
        plan = specialist.build_plan(request, hosts)
        if plan is not None:
            definition = get_agent_definition(str(plan.raw.get("specialist") or ""))
            if definition is not None:
                plan.raw.setdefault("agent_title", definition.title)
                plan.raw.setdefault("agent_definition_path", str(definition.source_path or ""))
            return plan, specialist.name

    return create_execution_plan(request=request, hosts=hosts, config=config, thread=thread), "planner"
