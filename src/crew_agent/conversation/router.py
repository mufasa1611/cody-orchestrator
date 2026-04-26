from __future__ import annotations

import re
from dataclasses import dataclass, field

from crew_agent.conversation.ollama import OllamaClient
from crew_agent.core.models import AppConfig


CHAT_PATTERNS = (
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "what is your name",
    "who are you",
    "do you know your name",
    "how are you",
)

HELP_PATTERNS = (
    "help",
    "?",
    "what can you do",
    "show help",
    "how do i use you",
    "what commands do you have",
)

ACTION_HINTS = (
    "check",
    "show",
    "list",
    "get",
    "read",
    "open",
    "search",
    "find",
    "grep",
    "inspect",
    "run",
    "test",
    "tests",
    "pytest",
    "unittest",
    "create",
    "write",
    "save",
    "make",
    "insert",
    "append",
    "edit",
    "modify",
    "replace",
    "remember",
    "note down",
    "restart",
    "start",
    "stop",
    "status",
    "version",
    "how many",
    "how much",
    "count",
    "installed",
    "available",
    "present",
    "exists",
    "install",
    "remove",
    "delete",
    "cleanup",
    "clean up",
    "wipe",
    "disk",
    "drive",
    "partition",
    "volume",
    "space",
    "service",
    "process",
    "port",
    "memory",
    "cpu",
    "repo",
    "repository",
    "code",
    "codebase",
    "git",
    "diff",
    "host",
    "server",
    "windows",
    "linux",
    "powershell",
    "cli",
    "command",
    "network",
    "log",
    "file",
    "folder",
    "directory",
    "path",
    "shutdown",
    "shut down",
    "show down",
    "shout down",
    "restart",
    "reboot",
)

TASK_CATEGORIES = {
    "disk",
    "service",
    "system",
    "network",
    "process",
    "package",
    "file",
    "code",
    "other",
}

TASK_ACTIONS = {"inspect", "change"}

ROUTER_SYSTEM_PROMPT = """
You are Cody's front-door request router.

Classify the user's message into exactly one route:
- chat: normal conversation, greetings, identity questions, casual questions
- help: asks how Cody works or what commands/features it has
- task: an operational infrastructure request that could be planned or executed
- reject: vague, unsafe-to-interpret, or non-actionable input

Rules:
- Do not invent infrastructure actions for chat or casual questions.
- Questions like "hi", "hello", "how are you", "what is your name", "do you know your name" are chat.
- Questions about Cody's usage, commands, models, permissions, approvals, inventory, or shell features are help.
- A task must contain a concrete operational intent such as inspect/check/show/list or change/restart/install/stop/remove/cleanup/wipe.
- System maintenance and cleaning up resources (temp files, caches, logs) are valid tasks.
- If the request is too vague to execute safely, route=reject.
- For task routes, normalize the request into a short operational sentence without changing intent.
- Keep replies short. Do not include hidden reasoning.

Return JSON only with this schema:
{
  "route": "chat|help|task|reject",
  "reply": "short user-facing reply",
  "normalized_request": "normalized operational request or empty string",
  "reason": "short routing reason",
  "confidence": "low|medium|high",
  "task_category": "disk|service|system|network|process|package|file|other",
  "action": "inspect|change|question|unknown",
  "target_hint": "optional target host or scope",
  "needs_clarification": false
}
""".strip()


@dataclass(frozen=True)
class RequestIntent:
    kind: str
    message: str


@dataclass(frozen=True)
class RouteDecision:
    kind: str
    message: str = ""
    normalized_request: str = ""
    reason: str = ""
    confidence: str = "medium"
    task_category: str = "other"
    action: str = "unknown"
    target_hint: str = ""
    needs_clarification: bool = False
    raw: dict = field(default_factory=dict)


def classify_request(request: str) -> RequestIntent:
    normalized = " ".join(request.casefold().split())
    if not normalized:
        return RequestIntent("unknown", "Enter a concrete infrastructure task.")

    if normalized in HELP_PATTERNS or normalized.startswith("help "):
        return RequestIntent(
            "help",
            "Use a concrete request like 'check disk space on local-win' or 'restart the audio service on local-win'.",
        )

    if normalized in CHAT_PATTERNS or any(
        normalized.startswith(prefix) for prefix in ("hi ", "hello ", "hey ")
    ):
        if "name" in normalized or "who are you" in normalized:
            return RequestIntent(
                "chat",
                "I am Cody. Give me a concrete task and I will plan it, run it, and report back clearly.",
            )
        return RequestIntent(
            "chat",
            "Give me a concrete task to inspect or change.",
        )

    # ULTIMATE PRO OVERRIDE: 
    # If we reached here, it's not a greeting and not a help request.
    # We FORCE it to be an orchestration task. The user is the boss.
    return RequestIntent("orchestrate", "")


def route_request(request: str, config: AppConfig) -> RouteDecision:
    fallback = _fallback_route(request)
    try:
        client = OllamaClient(
            model=config.model,
            base_url=config.base_url,
            timeout=min(config.planner_timeout_seconds, 45),
        )
        data = client.generate_json(ROUTER_SYSTEM_PROMPT, request)
        decision = _normalize_route_decision(data, request)
        validated = validate_route_decision(decision, request)
        if validated is not None:
            return validated
        return fallback
    except Exception:
        return fallback


def validate_route_decision(decision: RouteDecision, original_request: str) -> RouteDecision | None:
    if decision.kind in {"chat", "help"} and _looks_task_like_request(original_request):
        return None

    if decision.kind in {"chat", "help"}:
        return decision

    if decision.kind == "reject":
        if _looks_task_like_request(original_request):
            return None
        if decision.message:
            return decision
        return RouteDecision(
            kind="reject",
            message="I need a concrete infrastructure task with a system target, state check, or change request.",
            reason=decision.reason or "router rejected the request",
            confidence=decision.confidence,
            raw=decision.raw,
        )

    if decision.kind != "task":
        return None

    normalized = decision.normalized_request or original_request
    
    # NEW PRO LOGIC: If it looks like a task, ignore the 'needs_clarification' flag
    if decision.needs_clarification and not _looks_task_like_request(original_request):
        return RouteDecision(
            kind="reject",
            message="That request is not specific enough to execute safely. Rephrase it as a concrete infrastructure task.",
            reason=decision.reason or "router requested clarification",
            confidence=decision.confidence,
            raw=decision.raw,
        )
    
    # If the action is unknown but it looks task-like, force 'inspect'
    action = decision.action
    if action not in TASK_ACTIONS and _looks_task_like_request(original_request):
        action = _infer_action(original_request)

    if action not in TASK_ACTIONS:
        return None
    
    # Final pass: If it looks operational, let it through
    if not (decision.task_category in TASK_CATEGORIES or _looks_operational(normalized)):
        return None

    return RouteDecision(
        kind="task",
        message=decision.message,
        normalized_request=normalized,
        reason=decision.reason,
        confidence=decision.confidence,
        task_category=decision.task_category,
        action=action,
        target_hint=decision.target_hint,
        needs_clarification=False,
        raw=decision.raw,
    )


def _normalize_route_decision(data: dict, original_request: str) -> RouteDecision:
    route = str(data.get("route") or "").strip().lower()
    if route not in {"chat", "help", "task", "reject"}:
        route = "reject"
    reply = str(data.get("reply") or "").strip()
    normalized_request = str(data.get("normalized_request") or "").strip()
    reason = str(data.get("reason") or "").strip()
    confidence = str(data.get("confidence") or "medium").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    task_category = str(data.get("task_category") or "other").strip().lower()
    action = str(data.get("action") or "unknown").strip().lower()
    target_hint = str(data.get("target_hint") or "").strip()
    needs_clarification = bool(data.get("needs_clarification", False))

    if route == "task" and not normalized_request:
        normalized_request = original_request

    return RouteDecision(
        kind=route,
        message=reply,
        normalized_request=normalized_request,
        reason=reason,
        confidence=confidence,
        task_category=task_category,
        action=action,
        target_hint=target_hint,
        needs_clarification=needs_clarification,
        raw=data if isinstance(data, dict) else {},
    )


def _fallback_route(request: str) -> RouteDecision:
    intent = classify_request(request)
    if intent.kind == "help":
        return RouteDecision(
            kind="help",
            message=intent.message,
            reason="local fallback classified the request as help",
            confidence="medium",
        )
    if intent.kind == "chat":
        return RouteDecision(
            kind="chat",
            message=intent.message,
            reason="local fallback classified the request as chat",
            confidence="medium",
        )
    if intent.kind == "unknown":
        return RouteDecision(
            kind="reject",
            message=intent.message,
            reason="local fallback rejected the request as non-operational",
            confidence="medium",
        )
    return RouteDecision(
        kind="task",
        normalized_request=request.strip(),
        reason="local fallback classified the request as operational",
        confidence="low",
        task_category=_infer_task_category(request),
        action=_infer_action(request),
    )


def _looks_operational(text: str) -> bool:
    lowered = " ".join(text.casefold().split())
    if any(term in lowered for term in ("search", "find", "locate", "where is")):
        return True
    return _infer_action(lowered) in TASK_ACTIONS and (
        any(hint in lowered for hint in ACTION_HINTS) or _looks_install_check_request(lowered)
    )


def _looks_task_like_request(text: str) -> bool:
    lowered = " ".join(text.casefold().split())
    return _looks_operational(lowered) or _looks_like_workspace_write(lowered) or _looks_install_check_request(lowered)


def _looks_like_workspace_write(lowered: str) -> bool:
    write_terms = ("create", "write", "save", "make", "insert", "append", "edit", "modify", "replace", "remember", "note down", "keep")
    file_terms = ("file", ".md", ".txt", "memo", "note", "memory")
    return any(term in lowered for term in write_terms) and any(term in lowered for term in file_terms)


def _infer_action(text: str) -> str:
    lowered = " ".join(text.casefold().split())
    if any(word in lowered for word in ("check", "show", "list", "get", "read", "open", "search", "find", "grep", "inspect", "status", "version", "how much", "how many", "run tests", "run the tests", "pytest", "unittest")):
        return "inspect"
    if _looks_install_check_request(lowered):
        return "inspect"
    if _looks_like_shutdown_reason_query(lowered):
        return "inspect"
    if any(word in lowered for word in ("create", "write", "save", "make", "insert", "append", "edit", "modify", "replace", "remember", "restart", "start", "stop", "install", "remove", "delete", "disable", "enable", "set", "update", "change", "cleanup", "clean up", "wipe")):
        return "change"
    return "unknown"


def _infer_task_category(text: str) -> str:
    lowered = " ".join(text.casefold().split())
    if any(word in lowered for word in ("disk", "drive", "volume", "partition", "space", "storage", "hd")):
        return "disk"
    if "service" in lowered:
        return "service"
    if any(word in lowered for word in ("windows", "linux", "os", "operating system", "powershell", "hostname", "computer")):
        return "system"
    if any(word in lowered for word in ("network", "port", "ping", "dns", "ip", "firewall")):
        return "network"
    if any(word in lowered for word in ("process", "task", "cpu", "memory", "ram")):
        return "process"
    if any(word in lowered for word in ("package", "install", "uninstall", "apt", "yum", "dnf", "choco", "winget")):
        return "package"
    if any(word in lowered for word in ("file", "folder", "directory", "path", "log")):
        return "file"
    if any(word in lowered for word in ("repo", "repository", "code", "codebase", "test", "tests", "pytest", "unittest", "git", "diff", "function", "class", "method")):
        return "code"
    if _looks_like_shutdown_reason_query(lowered):
        return "system"
    return "other"


def _looks_like_shutdown_reason_query(lowered: str) -> bool:
    shutdown_terms = ("shutdown", "shut down", "show down", "shout down", "power off", "restart", "reboot")
    reason_terms = ("reason", "why", "last time", "previous", "last")
    return any(term in lowered for term in shutdown_terms) and any(term in lowered for term in reason_terms)


def _looks_install_check_request(lowered: str) -> bool:
    install_terms = ("installed", "available", "present", "exist", "exists", "in path")
    target_terms = ("cli", "command", "tool", "github", "git", "gh", "python", "powershell", "windows")
    question_terms = ("is ", "does ", "can ", "check", "show", "tell me")
    return (
        any(term in lowered for term in install_terms)
        and any(term in lowered for term in target_terms)
        and any(term in lowered for term in question_terms)
    )
