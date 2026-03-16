"""LLM execution — llm, source, . commands."""

from __future__ import annotations

import time

from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor.handler import get_config
from cogos.files.store import FileStore
from cogos.runtime.local import run_and_complete
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.files import _resolve_path


def _execute_prompt(state: ShellState, content: str) -> str:
    """Create a temp process, execute the prompt, return output."""
    ts = int(time.time())
    proc_name = f"shell-{ts}"

    process = Process(
        name=proc_name,
        mode=ProcessMode.ONE_SHOT,
        content=content,
        runner="local",
        status=ProcessStatus.RUNNING,
    )
    state.repo.upsert_process(process)

    run = Run(process=process.id, status=RunStatus.RUNNING)
    state.repo.create_run(run)

    config = get_config()
    run = run_and_complete(
        process, {}, run, config, state.repo,
        bedrock_client=state.bedrock_client,
    )

    state.repo.update_process_status(process.id, ProcessStatus.COMPLETED)

    lines = []
    if run.result:
        lines.append(run.result)
    lines.append(
        f"\n\033[90mtokens: {run.tokens_in or 0} in, {run.tokens_out or 0} out"
        f" ({run.duration_ms or 0}ms)\033[0m"
    )
    if run.status == RunStatus.FAILED:
        lines.append(f"\033[31mError: {run.error}\033[0m")
    return "\n".join(lines)


def _execute_interactive(state: ShellState, initial_content: str = "") -> str:
    """Interactive multi-turn LLM session."""
    from prompt_toolkit import PromptSession

    session: PromptSession = PromptSession()
    lines = []

    if initial_content:
        lines.append(f"\033[90m(loaded context: {len(initial_content)} chars)\033[0m")
        output = _execute_prompt(state, initial_content)
        lines.append(output)

    try:
        while True:
            try:
                user_input = session.prompt("llm> ")
            except EOFError:
                break
            if user_input.strip() in ("/exit", "exit", "quit"):
                break
            if not user_input.strip():
                continue
            output = _execute_prompt(state, user_input)
            lines.append(output)
    except KeyboardInterrupt:
        pass

    return "\n".join(lines) if lines else "(session ended)"


def register(reg: CommandRegistry) -> None:

    @reg.register("llm", help="Run an LLM prompt: llm <text> | llm -f <file> | llm -i")
    def llm(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: llm <prompt> | llm -f <file> | llm -i [-f <file>]"

        interactive = "-i" in args
        file_path = None
        prompt_parts = []

        i = 0
        while i < len(args):
            if args[i] == "-i":
                i += 1
            elif args[i] == "-f" and i + 1 < len(args):
                file_path = args[i + 1]
                i += 2
            else:
                prompt_parts.append(args[i])
                i += 1

        content = ""
        if file_path:
            key = _resolve_path(state, file_path)
            fs = FileStore(state.repo)
            file_content = fs.get_content(key)
            if file_content is None:
                return f"File not found: {file_path}"
            content = file_content

        if prompt_parts:
            inline = " ".join(prompt_parts)
            content = f"{content}\n\n{inline}" if content else inline

        if interactive:
            return _execute_interactive(state, content)

        if not content:
            return "Usage: llm <prompt> | llm -f <file>"

        return _execute_prompt(state, content)

    @reg.register("source", aliases=["."], help="Execute a file as an LLM prompt")
    def source(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: source <file>"
        key = _resolve_path(state, args[0])
        fs = FileStore(state.repo)
        content = fs.get_content(key)
        if content is None:
            return f"File not found: {args[0]}"
        return _execute_prompt(state, content)
