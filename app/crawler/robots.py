from __future__ import annotations

from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser


class RobotsPolicy:
    def __init__(self, parser: RobotFileParser, user_agent: str):
        self.parser = parser
        self.user_agent = user_agent

    @classmethod
    def for_url(cls, url: str, user_agent: str) -> "RobotsPolicy":
        parser = RobotFileParser()
        parser.set_url(urljoin(url, "/robots.txt"))
        try:
            parser.read()
        except OSError:
            # Conservative enough for unreachable robots: robotparser treats no rules as allowed.
            pass
        return cls(parser, user_agent)

    def can_fetch(self, url: str) -> bool:
        return self.parser.can_fetch(self.user_agent, url)

