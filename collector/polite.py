"""Polite HTTP: clear user agent, ~1 request/second per host, robots.txt respected."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests


class RobotsDisallowed(Exception):
    pass


class PoliteSession:
    def __init__(self, user_agent: str, delay: float = 1.0, timeout: float = 30):
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _wait_turn(self, host: str) -> None:
        # Caller holds the host lock, so requests to one host are serialized and spaced.
        elapsed = time.monotonic() - self._last_hit.get(host, 0.0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_hit[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                self._wait_turn(parts.netloc)
                r = self._session.get(origin + "/robots.txt", timeout=self.timeout)
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp = None  # no robots file: everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return rp is None or rp.can_fetch(self.user_agent, url)

    def get(self, url: str, *, check_robots: bool = True, **kwargs) -> requests.Response:
        host = urlsplit(url).netloc
        with self._host_lock(host):
            if check_robots and not self._allowed(url):
                raise RobotsDisallowed(f"robots.txt disallows {url}")
            self._wait_turn(host)
            kwargs.setdefault("timeout", self.timeout)
            resp = self._session.get(url, **kwargs)
        resp.raise_for_status()
        return resp
