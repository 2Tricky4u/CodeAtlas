"""Claude Agent SDK engine (ADR-0005).

Runs each task as a fresh session against the installed `claude` CLI using the
user's subscription auth — no API key, no per-token billing. Enforcement is
structural rather than advisory:

- `cwd` is the pinned read-only checkout;
- `allowed_tools` is derived from the skill's declared permissions, and a
  `can_use_tool` callback denies anything outside them (network tools always);
- output must validate against the task's schema or the result is
  `schema_invalid`. The engine validates once; the one bounded repair attempt
  lives at dispatch level (`dispatch_with_retry`), where the retry lands its
  own invocation row instead of hiding inside this session;
- `max_turns` and a wall-clock timeout bound the run.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from codeatlas.agents.engine import EngineHealth, validate_output

if TYPE_CHECKING:
    from claude_agent_sdk import HookCallback
from codeatlas.core.logging import get_logger
from codeatlas.models.agent import AgentResult, AgentTask, CommandReceipt, UsageStats

log = get_logger("codeatlas.agents.claude")

# Tools that can reach the network or mutate state outside the task output dir.
_NETWORK_TOOLS = frozenset({"WebFetch", "WebSearch"})
_WRITE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})
_READ_TOOLS = ("Read", "Grep", "Glob")

_JSON_BLOCK = re.compile(r"```json\s*(.*?)```", re.DOTALL)


class ClaudeAgentEngine:
    name = "claude-agent-sdk"

    def __init__(self, model: str | None = None, cas: Any | None = None) -> None:
        self.model = model
        # Resolves the task's content-addressed inputs so their CONTENT can be
        # inlined into the prompt. Without it an agent receives hashes it cannot
        # dereference — see _build_prompt.
        self.cas = cas

    def _resolve_inputs(self, task: AgentTask) -> dict[str, Any] | None:
        """Dereference each input to the content the agent will actually see.

        Not every input is JSON. A unified diff is plain text, and treating a
        failed `json.loads` as an unresolvable input discarded *every* input for
        that task — the agent then reasoned with nothing, which is precisely the
        failure this inlining was introduced to fix. Non-JSON content is passed
        through as text; only a genuinely missing artifact is unresolvable.
        """
        if self.cas is None or not task.inputs:
            return None
        resolved: dict[str, Any] = {}
        for name, ref in task.inputs.items():
            try:
                raw = self.cas.get(ref)
            except KeyError as exc:
                log.error("agent.input_missing", input=name, ref=ref, error=str(exc))
                return None
            try:
                resolved[name] = json.loads(raw)
            except ValueError:
                resolved[name] = raw.decode("utf-8", "replace")
        return resolved

    def health_check(self) -> EngineHealth:
        import shutil

        if shutil.which("claude") is None:
            return EngineHealth(available=False, detail="claude CLI not on PATH")
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as exc:  # pragma: no cover - dependency is declared
            return EngineHealth(available=False, detail=f"SDK import failed: {exc}")
        return EngineHealth(available=True, detail="claude CLI + SDK present")

    def run(self, task: AgentTask, instructions: str) -> AgentResult:
        return asyncio.run(self._run_async(task, instructions))

    async def _run_async(self, task: AgentTask, instructions: str) -> AgentResult:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            HookMatcher,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
        )

        receipts: list[CommandReceipt] = []
        denials: list[str] = []

        allowed_tools = [*_READ_TOOLS]
        if task.permissions.allowed_commands:
            allowed_tools.append("Bash")

        # A PreToolUse hook (not can_use_tool) is the enforcement point: entries in
        # allowed_tools auto-approve a whole tool BEFORE can_use_tool is consulted,
        # which would make the Bash allowlist decorative. Hooks see every call.
        async def pre_tool_use(
            input_data: Any, tool_use_id: str | None, context: Any
        ) -> dict[str, Any]:
            tool_name = str(input_data.get("tool_name", ""))
            tool_input = input_data.get("tool_input") or {}
            reason = _permission_violation(tool_name, tool_input, task)
            if reason is None:
                return {}
            denials.append(f"{tool_name}: {reason}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }

        options = ClaudeAgentOptions(
            cwd=str(Path(task.workspace.checkout_path)),
            allowed_tools=allowed_tools,
            disallowed_tools=sorted(_NETWORK_TOOLS),
            hooks={"PreToolUse": [HookMatcher(hooks=[cast("HookCallback", pre_tool_use)])]},
            max_turns=task.limits.max_iterations,
            permission_mode="default",
            model=self.model,
            setting_sources=[],  # ignore user/project settings: the skill is the instruction set
        )

        prompt = _build_prompt(task, instructions, self._resolve_inputs(task))
        started = time.monotonic()
        text_parts: list[str] = []
        files_read: set[str] = set()
        usage = UsageStats(
            prompt_tokens=0, completion_tokens=0, cost_usd=None, wall_ms=0, model_id="unknown"
        )
        structured: dict[str, Any] | None = None
        error: str | None = None

        try:
            async with asyncio.timeout(task.limits.timeout_s):
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt)
                    async for message in client.receive_response():
                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    text_parts.append(block.text)
                                elif isinstance(block, ToolUseBlock) and block.name == "Bash":
                                    receipts.append(
                                        CommandReceipt(
                                            command=str(block.input.get("command", ""))[:500],
                                            exit_code=0,
                                            duration_ms=0,
                                        )
                                    )
                                elif isinstance(block, ToolUseBlock) and block.name == "Read":
                                    # Measured coverage: the engine watches the
                                    # tool stream; the model never self-reports.
                                    raw = str(block.input.get("file_path", ""))
                                    if raw:
                                        files_read.add(
                                            normalize_read_path(raw, task.workspace.checkout_path)
                                        )
                        elif isinstance(message, ResultMessage):
                            usage = _usage_from(message)
                            structured = getattr(message, "structured_output", None)
        except TimeoutError:
            return _failed(task, "timeout", receipts, usage, started, "wall-clock timeout", denials)
        except Exception as exc:
            log.error("agent.engine_error", task_id=task.task_id, error=str(exc))
            return _failed(task, "failed", receipts, usage, started, str(exc)[:1000], denials)

        payload = (
            structured if isinstance(structured, dict) else _extract_json("\n".join(text_parts))
        )
        errors = validate_output(payload, task.output_schema_id)
        if errors:
            error = "; ".join(errors[:5])
            status = "schema_invalid"
            payload = None
        else:
            status = "succeeded"

        if denials:
            log.info("agent.permission_denials", task_id=task.task_id, denials=denials)

        return AgentResult(
            task_id=task.task_id,
            status=status,  # type: ignore[arg-type]
            output=payload,
            command_receipts=receipts,
            usage=usage.model_copy(update={"wall_ms": int((time.monotonic() - started) * 1000)}),
            permission_denials=denials,
            transcript_ref=None,
            error=error,
            files_read=sorted(files_read),
        )


def normalize_read_path(raw: str, checkout_path: str) -> str:
    """Repo-relative forward-slash when inside the checkout; verbatim-posix otherwise.

    Honesty over prettiness: a read outside the pinned checkout stays visible
    as the absolute path it was, rather than being prettified into looking
    like repository content.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(Path(checkout_path)).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _permission_violation(
    tool_name: str, tool_input: dict[str, Any], task: AgentTask
) -> str | None:
    """The reason this tool call must be denied, or None if it is permitted."""
    if tool_name in _NETWORK_TOOLS:
        return "network access is not permitted for this task"
    if tool_name in _WRITE_TOOLS:
        target = str(tool_input.get("file_path", ""))
        if not _within(target, task.permissions.write_paths):
            return f"write path not permitted: {target[:200]}"
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if not _command_allowed(command, task.permissions.allowed_commands):
            return f"command not in the task allowlist: {command[:200]}"
    return None


MAX_INLINE_INPUT_CHARS = 60_000


def _build_prompt(
    task: AgentTask, instructions: str, resolved_inputs: dict[str, Any] | None = None
) -> str:
    """The prompt an agent actually sees.

    Inputs are inlined as CONTENT, not as content-addressed hashes. An agent has
    no way to dereference a sha256, so passing bare hashes silently starved every
    stage of its evidence — the finding-validator was echoing the hash back as a
    finding id rather than ruling on the finding, because it had never seen one.
    Hashes remain in the task for provenance and cassette keying.
    """
    sections = [
        instructions,
        "",
        "## Task",
        f"- revision: {task.revision_sha}",
        "- workspace: the current working directory (read-only checkout)",
    ]

    if resolved_inputs:
        sections += ["", "## Inputs", ""]
        for name, value in sorted(resolved_inputs.items()):
            rendered = json.dumps(value, indent=2, sort_keys=True)
            if len(rendered) > MAX_INLINE_INPUT_CHARS:
                rendered = (
                    rendered[:MAX_INLINE_INPUT_CHARS]
                    + f"\n... TRUNCATED at {MAX_INLINE_INPUT_CHARS} characters; "
                    "the remainder was not provided, so do not assume anything about it."
                )
            sections += [f"### {name}", "```json", rendered, "```", ""]
    elif task.inputs:
        sections += ["", f"- input references: {json.dumps(task.inputs, sort_keys=True)}"]

    sections += [
        "",
        "## Output contract",
        f"Reply with ONE fenced ```json block validating against `{task.output_schema_id}`. "
        "No prose outside the block. Every claim must cite a file path and line range that "
        "exists at this revision.",
        "",
    ]
    return "\n".join(sections)


def _usage_from(message: object) -> UsageStats:
    raw = getattr(message, "usage", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    return UsageStats(
        prompt_tokens=int(raw.get("input_tokens", 0) or 0),
        completion_tokens=int(raw.get("output_tokens", 0) or 0),
        cost_usd=getattr(message, "total_cost_usd", None),
        wall_ms=int(getattr(message, "duration_ms", 0) or 0),
        model_id=str(_first_model(getattr(message, "model_usage", None)) or "claude"),
    )


def _first_model(model_usage: object) -> str | None:
    if isinstance(model_usage, dict) and model_usage:
        return str(next(iter(model_usage)))
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    match = _JSON_BLOCK.search(text)
    candidate = match.group(1) if match else text.strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _within(target: str, permitted: list[str]) -> bool:
    if not target or not permitted:
        return False
    target_path = Path(target).resolve()
    for allowed in permitted:
        try:
            target_path.relative_to(Path(allowed).resolve())
            return True
        except ValueError:
            continue
    return False


def _command_allowed(command: str, allowlist: list[str]) -> bool:
    stripped = command.strip()
    if not stripped or not allowlist:
        return False
    # Reject shell chaining outright: an allowlisted prefix must describe the
    # whole command, not just its first segment.
    if any(token in stripped for token in ("&&", "||", ";", "|", "`", "$(")):
        return False
    return any(stripped == allowed or stripped.startswith(allowed + " ") for allowed in allowlist)


def _failed(
    task: AgentTask,
    status: str,
    receipts: list[CommandReceipt],
    usage: UsageStats,
    started: float,
    error: str,
    denials: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        task_id=task.task_id,
        status=status,  # type: ignore[arg-type]
        output=None,
        command_receipts=receipts,
        usage=usage.model_copy(update={"wall_ms": int((time.monotonic() - started) * 1000)}),
        permission_denials=denials or [],
        transcript_ref=None,
        error=error,
    )
