from __future__ import annotations

from collections.abc import Callable
from typing import Optional

import grpc
from rich.console import Console
from rich.text import Text


def error_message(error: BaseException, verbose: bool = False) -> str:
    """Return a concise user-facing message for an exception."""
    if not isinstance(error, grpc.RpcError):
        return str(error) or error.__class__.__name__

    details = error.details()
    message = details or "The device did not provide an error message."
    if not verbose:
        return message

    code = error.code()
    code_name = getattr(code, "name", str(code)) if code is not None else "UNKNOWN"
    return f"gRPC {code_name}: {message}"


def print_error(
    console: Console,
    error: BaseException,
    *,
    context: Optional[str] = None,
    verbose: bool = False,
) -> None:
    message = error_message(error, verbose=verbose)
    prefix = f"{context}: " if context else ""
    console.print("[bold red]Error:[/bold red]", Text(f"{prefix}{message}"))


def run_action(
    action: Callable[[], object],
    *,
    console: Console,
    verbose: bool = False,
) -> int:
    """Run a parsed CLI action and translate runtime failures to exit codes."""
    try:
        result = action()
        return 1 if result is False else 0
    except KeyboardInterrupt:
        console.print("[yellow]Operation cancelled.[/yellow]")
        return 130
    except grpc.RpcError as error:
        print_error(console, error, verbose=verbose)
        return 1
    except Exception as error:
        print_error(console, error)
        if verbose:
            console.print_exception(show_locals=False)
        return 1
