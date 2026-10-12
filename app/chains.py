"""Chains: saved agents run one after another, each receiving the previous one's result
(variable {resultat_precedent}) and downloaded files (as attachments).

A chain stops at the first failed step unless that step says "continue". Steps are ordinary
runs (visible in Exécutions, with their own detail page), linked to the chain run.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime

from . import agents, config, files
from .db import connect

logger = logging.getLogger(__name__)

MAX_STEPS_PER_CHAIN = 10
ACTIVE = ("en_attente", "en_cours", "a_valider")
FINAL_RUN = ("termine", "echec", "arrete", "interrompu")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- saved chains ------------------------------------------------------------------------


def _decode(row) -> dict | None:
    if not row:
        return None
    chain = dict(row)
    chain["steps"] = json.loads(chain["steps"])
    chain["schedule"] = json.loads(chain["schedule"]) if chain.get("schedule") else None
    chain["schedule_enabled"] = bool(chain["schedule_enabled"])
    return chain


def list_for(owner: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM chains WHERE owner = ? ORDER BY name COLLATE NOCASE", (owner,)).fetchall()
    return [_decode(r) for r in rows]


def list_all() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM chains ORDER BY name COLLATE NOCASE").fetchall()
    return [_decode(r) for r in rows]


def get(chain_id: str, owner: str) -> dict | None:
    with connect() as conn:
        return _decode(conn.execute("SELECT * FROM chains WHERE id = ? AND owner = ?", (chain_id, owner)).fetchone())


def validate_steps(steps: list[dict], owner: str) -> tuple[list[dict], str | None]:
    if not steps:
        return [], "Ajoutez au moins une étape."
    if len(steps) > MAX_STEPS_PER_CHAIN:
        return [], f"{MAX_STEPS_PER_CHAIN} étapes au maximum."
    out = []
    for step in steps:
        agent_id = str(step.get("agent_id") or "")
        if not agents.get(agent_id, owner):
            return [], "Une étape désigne un agent introuvable : choisissez-en un autre."
        out.append({"agent_id": agent_id, "on_failure": "continue" if step.get("on_failure") == "continue" else "stop"})
    return out, None


def _next_run_at(schedule_def: dict | None, enabled: bool) -> str | None:
    from .schedule import next_run

    return next_run(schedule_def, datetime.now()).isoformat(timespec="seconds") if schedule_def and enabled else None


def create(owner: str, name: str, steps: list[dict], schedule_def: dict | None, schedule_enabled: bool, via: str = "app") -> dict:
    now = _now()
    row = {"id": uuid.uuid4().hex[:12], "owner": owner, "name": name, "steps": json.dumps(steps),
           "schedule": json.dumps(schedule_def) if schedule_def else None,
           "schedule_enabled": int(bool(schedule_def) and schedule_enabled),
           "next_run_at": _next_run_at(schedule_def, schedule_enabled), "created_at": now, "updated_at": now,
           "created_via": via, "updated_via": via}
    with connect() as conn:
        conn.execute(f"INSERT INTO chains ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})", row)
    return _decode(row)


def update(chain_id: str, owner: str, changes: dict, via: str = "app") -> dict | None:
    current = get(chain_id, owner)
    if not current:
        return None
    merged = {**current, **{k: v for k, v in changes.items() if k in ("name", "steps", "schedule", "schedule_enabled")}}
    enabled = bool(merged["schedule"]) and merged["schedule_enabled"]
    sets = {"name": merged["name"], "steps": json.dumps(merged["steps"]),
            "schedule": json.dumps(merged["schedule"]) if merged["schedule"] else None,
            "schedule_enabled": int(enabled), "updated_at": _now(), "updated_via": via}
    if merged["schedule"] != current["schedule"] or enabled != current["schedule_enabled"]:
        sets["next_run_at"] = _next_run_at(merged["schedule"], enabled)
    with connect() as conn:
        conn.execute(f"UPDATE chains SET {', '.join(f'{k} = :{k}' for k in sets)} WHERE id = :id AND owner = :owner",
                     {**sets, "id": chain_id, "owner": owner})
    return get(chain_id, owner)


def delete(chain_id: str, owner: str) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM chains WHERE id = ? AND owner = ?", (chain_id, owner)).rowcount > 0


# --- running a chain -----------------------------------------------------------------------


class ChainRun:
    def __init__(self, chain: dict, trigger: str):
        self.id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.owner = chain["owner"]
        self.chain_id = chain["id"]
        self.chain_name = chain["name"]
        self.status = "en_cours"
        self.trigger = trigger
        self.created_at = _now()
        self.finished_at: str | None = None
        self.stop_requested = False
        names = {a["id"]: a["name"] for a in agents.list_for(self.owner)}
        self.steps = [{"agent_id": s["agent_id"], "agent_name": names.get(s["agent_id"], "Agent supprimé"),
                       "on_failure": s["on_failure"], "run_id": None, "status": "a_venir", "result": None}
                      for s in chain["steps"]]

    @classmethod
    def from_row(cls, row) -> "ChainRun":
        run = cls.__new__(cls)
        for key in ("id", "owner", "chain_id", "chain_name", "status", "trigger", "created_at", "finished_at"):
            setattr(run, key, row[key])
        run.steps = json.loads(row["steps"])
        run.stop_requested = False
        return run

    @property
    def current_step(self) -> int | None:
        return next((i for i, s in enumerate(self.steps) if s["status"] in ACTIVE), None)

    def summary(self) -> dict:
        done = sum(1 for s in self.steps if s["status"] in FINAL_RUN)
        return {"id": self.id, "owner": self.owner, "chain_id": self.chain_id, "chain_name": self.chain_name, "status": self.status,
                "trigger": self.trigger, "created_at": self.created_at, "finished_at": self.finished_at,
                "steps": self.steps, "current_step": self.current_step, "done_steps": done, "total_steps": len(self.steps)}

    def save(self) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO chain_runs (id, owner, chain_id, chain_name, status, trigger, created_at, finished_at, steps)"
                " VALUES (:id, :owner, :chain_id, :chain_name, :status, :trigger, :created_at, :finished_at, :steps)"
                " ON CONFLICT(id) DO UPDATE SET status = :status, finished_at = :finished_at, steps = :steps",
                {"id": self.id, "owner": self.owner, "chain_id": self.chain_id, "chain_name": self.chain_name,
                 "status": self.status, "trigger": self.trigger, "created_at": self.created_at,
                 "finished_at": self.finished_at, "steps": json.dumps(self.steps, ensure_ascii=False)},
            )


class ChainManager:
    def __init__(self, manager):
        self.manager = manager  # the TaskManager that runs each step
        self.runs: dict[str, ChainRun] = {}
        self._load()

    def _load(self) -> None:
        with connect() as conn:
            conn.execute("UPDATE chain_runs SET status = 'interrompu', finished_at = COALESCE(finished_at, ?)"
                         " WHERE status = 'en_cours'", (_now(),))
            rows = conn.execute("SELECT * FROM chain_runs ORDER BY created_at").fetchall()
        for row in rows:
            self.runs[row["id"]] = ChainRun.from_row(row)

    def runs_of(self, owner: str) -> list[ChainRun]:
        return [r for r in self.runs.values() if r.owner == owner]

    def start(self, chain: dict, trigger: str = "manuel") -> ChainRun:
        if any(r.chain_id == chain["id"] and r.status == "en_cours" for r in self.runs.values()):
            raise RuntimeError("Cette chaîne est déjà en cours d'exécution.")
        chain_run = ChainRun(chain, trigger)
        chain_run.save()
        self.runs[chain_run.id] = chain_run
        asyncio.create_task(self._execute(chain_run))
        return chain_run

    def stop(self, chain_run: ChainRun) -> None:
        chain_run.stop_requested = True
        index = chain_run.current_step
        if index is not None and chain_run.steps[index]["run_id"]:
            run = self.manager.runs.get(chain_run.steps[index]["run_id"])
            if run and run.status in ACTIVE:
                self.manager.stop(run)

    async def _execute(self, chain_run: ChainRun) -> None:
        previous_result, previous_files = None, []
        stopped_by_failure = False
        try:
            for index, step in enumerate(chain_run.steps):
                if chain_run.stop_requested:
                    break
                agent = agents.get(step["agent_id"], chain_run.owner)
                if not agent:
                    step.update(status="echec", result="Agent supprimé depuis la création de la chaîne.")
                    chain_run.save()
                    if step["on_failure"] == "stop":
                        stopped_by_failure = True
                        break
                    previous_result, previous_files = f"(l'étape « {step['agent_name']} » n'a pas pu s'exécuter : agent supprimé)", []
                    continue
                first = "(aucun résultat : c'est la première étape)"
                extra = {"resultat_precedent": previous_result or (first if index == 0 else "(l'étape précédente n'a rien renvoyé)")}
                options = {**agents.run_options(agent, trigger="chaine"),
                           "chain_run_id": chain_run.id, "chain_name": chain_run.chain_name}
                options["attachments"] = list(options.get("attachments") or []) + previous_files
                run = self.manager.start(owner=chain_run.owner, task=agents.render(agent["instructions"], extra=extra),
                                         headless=True, max_steps=agent["max_steps"] or config.AGENT_MAX_STEPS,
                                         agent_id=agent["id"], agent_name=agent["name"], options=options)
                step.update(run_id=run.id, status=run.status, agent_name=agent["name"])
                chain_run.save()
                while run.status not in FINAL_RUN:
                    await asyncio.sleep(1)
                    if step["status"] != run.status:
                        step["status"] = run.status
                        chain_run.save()
                step.update(status=run.status, result=run.result)
                chain_run.save()
                if run.status != "termine":
                    if chain_run.stop_requested or step["on_failure"] == "stop":
                        stopped_by_failure = not chain_run.stop_requested
                        break
                    # Continue anyway, but tell the next agent what happened instead of a stale result.
                    previous_result = f"(l'étape « {agent['name']} » a échoué : {run.result or 'sans détail'})"
                    previous_files = [run.downloads_dir / f["name"] for f in files.listing(run.downloads_dir)]
                    continue
                previous_result = run.result
                previous_files = [run.downloads_dir / f["name"] for f in files.listing(run.downloads_dir)]
        except Exception:
            logger.exception("Chain run %s failed", chain_run.id)
            stopped_by_failure = True
        for step in chain_run.steps:
            if step["status"] == "a_venir":
                step["status"] = "ignore"
        chain_run.status = "arrete" if chain_run.stop_requested else "echec" if stopped_by_failure else "termine"
        chain_run.finished_at = _now()
        chain_run.save()

    def tick(self, now: datetime, catch_up) -> list[str]:
        """Start the chains that are due (called by the scheduler)."""
        from .schedule import next_run

        with connect() as conn:
            due = conn.execute("SELECT * FROM chains WHERE schedule_enabled = 1 AND schedule IS NOT NULL"
                               " AND next_run_at IS NOT NULL AND next_run_at <= ?", (now.isoformat(timespec="seconds"),)).fetchall()
        started = []
        for row in due:
            chain = _decode(row)
            planned = datetime.fromisoformat(chain["next_run_at"])
            with connect() as conn:
                conn.execute("UPDATE chains SET next_run_at = ? WHERE id = ?",
                             (next_run(chain["schedule"], now).isoformat(timespec="seconds"), chain["id"]))
            if now - planned > catch_up:
                logger.warning("Chaîne %s : exécution du %s manquée, ignorée", chain["id"], planned)
                continue
            try:
                started.append(self.start(chain, trigger="planifie").id)
            except RuntimeError as e:
                logger.warning("Chaîne %s : lancement planifié refusé : %s", chain["id"], e)
        return started
