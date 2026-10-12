"""Plain-language schedules for agents, and the loop that launches them.

A schedule is a small JSON object:
    {"kind": "daily",    "time": "08:00"}                    every day
    {"kind": "weekdays", "time": "08:00"}                    Monday to Friday
    {"kind": "weekly",   "time": "08:00", "days": [0, 3]}    chosen weekdays (0 = Monday)
    {"kind": "monthly",  "time": "08:00", "monthday": 2}     day N of each month (-1 = last day)
"""

import asyncio
import calendar
import json
import logging
import re
from datetime import datetime, timedelta

from . import agents
from .db import connect

logger = logging.getLogger(__name__)

KINDS = ("daily", "weekdays", "weekly", "monthly")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
CHECK_SECONDS = 30
# A run missed by more than this (server off, PC asleep) is skipped instead of launched late.
CATCH_UP = timedelta(hours=6)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def validate(s: dict) -> str | None:
    if s.get("kind") not in KINDS:
        return "Fréquence inconnue."
    if not _TIME_RE.match(str(s.get("time", ""))):
        return "Heure invalide (format HH:MM)."
    if s["kind"] == "weekly":
        days = s.get("days") or []
        if not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            return "Choisissez au moins un jour de la semaine."
    if s["kind"] == "monthly":
        md = s.get("monthday")
        if not isinstance(md, int) or not (1 <= md <= 31 or md == -1):
            return "Jour du mois invalide (1 à 31, ou dernier jour)."
    return None


def normalize(s: dict) -> dict:
    out = {"kind": s["kind"], "time": s["time"]}
    if s["kind"] == "weekly":
        out["days"] = sorted(set(s["days"]))
    if s["kind"] == "monthly":
        out["monthday"] = s["monthday"]
    return out


def describe(s: dict | None) -> str:
    if not s:
        return "Non planifié"
    at = f"à {s['time'].replace(':', 'h')}"
    if s["kind"] == "daily":
        return f"Chaque jour {at}"
    if s["kind"] == "weekdays":
        return f"Du lundi au vendredi {at}"
    if s["kind"] == "weekly":
        names = [JOURS[d] for d in s["days"]]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1]
        return f"Chaque {listed} {at}"
    md = s["monthday"]
    day = "le dernier jour" if md == -1 else ("le 1er" if md == 1 else f"le {md}")
    return f"{day[0].upper()}{day[1:]} de chaque mois {at}"


def _monthday(year: int, month: int, md: int) -> int:
    last = calendar.monthrange(year, month)[1]
    return last if md == -1 else min(md, last)


def next_run(s: dict, after: datetime) -> datetime:
    """The first scheduled moment strictly after `after`."""
    hour, minute = map(int, s["time"].split(":"))
    if s["kind"] == "monthly":
        year, month = after.year, after.month
        for _ in range(14):
            candidate = datetime(year, month, _monthday(year, month, s["monthday"]), hour, minute)
            if candidate > after:
                return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    allowed = {"daily": range(7), "weekdays": range(5), "weekly": s.get("days", [])}[s["kind"]]
    day = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(8):
        if day > after and day.weekday() in allowed:
            return day
        day += timedelta(days=1)
    raise ValueError("Planification sans date possible")


# --- the loop -------------------------------------------------------------------


class Scheduler:
    def __init__(self, manager, default_max_steps: int):
        self.manager = manager
        self.default_max_steps = default_max_steps
        self.chain_manager = None  # set by main: scheduled chains are launched by the same loop
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(CHECK_SECONDS)

    def tick(self, now: datetime | None = None) -> list[str]:
        """Launch every agent that is due; returns the ids of the runs started."""
        now = now or datetime.now()
        with connect() as conn:
            due = conn.execute(
                "SELECT * FROM agents WHERE schedule_enabled = 1 AND schedule IS NOT NULL"
                " AND next_run_at IS NOT NULL AND next_run_at <= ?",
                (now.isoformat(timespec="seconds"),),
            ).fetchall()
        started = []
        for row in due:
            agent = agents.decode(dict(row))
            planned = datetime.fromisoformat(agent["next_run_at"])
            following = next_run(agent["schedule"], now)
            with connect() as conn:
                conn.execute("UPDATE agents SET next_run_at = ? WHERE id = ?", (following.isoformat(timespec="seconds"), agent["id"]))
            if now - planned > CATCH_UP:
                logger.warning("Agent %s: exécution du %s manquée (serveur arrêté), ignorée", agent["id"], planned)
                continue
            try:
                run = self.manager.start(
                    owner=agent["owner"],
                    task=agents.render(agent["instructions"]),
                    headless=True,
                    max_steps=agent["max_steps"] or self.default_max_steps,
                    agent_id=agent["id"],
                    agent_name=agent["name"],
                    options=agents.run_options(agent, trigger="planifie"),
                )
                started.append(run.id)
                logger.info("Agent %s lancé par la planification (exécution %s)", agent["id"], run.id)
            except RuntimeError as e:
                logger.warning("Agent %s: lancement planifié refusé: %s", agent["id"], e)
        if self.chain_manager:
            started += self.chain_manager.tick(now, CATCH_UP)
        return started


def dumps(s: dict | None) -> str | None:
    return json.dumps(s) if s else None
