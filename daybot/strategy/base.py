from __future__ import annotations

from abc import ABC, abstractmethod

from daybot.models import Bar, Position, Signal


class Strategy(ABC):
    """A strategy sees only *closed* bars of the current session and returns
    at most one signal per bar. Whatever it returns is executed at the next
    bar's open at the earliest, never at the close it was computed from."""

    name: str = "base"

    def reset(self) -> None:
        """Called at the start of every session."""

    def end_session(self, bars: list[Bar]) -> None:
        """Called once a session is over, with all of its bars. A strategy
        that needs earlier days (the previous close, a volatility history)
        records them here; nothing it does can reach the session just ended."""

    @abstractmethod
    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        ...

    def params(self) -> dict:
        return {}
