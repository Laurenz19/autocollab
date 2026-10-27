"""Regression tests; isolated data and no browser or model calls.

Run with: .venv\Scripts\python.exe -m unittest discover -s tests
"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

_sandbox = tempfile.TemporaryDirectory(prefix="autocollab-tests-")
os.environ.update({
    "AUTOCOLLAB_DATA_DIR": str(Path(_sandbox.name) / "data"),
    "AUTOCOLLAB_RUNS_DIR": str(Path(_sandbox.name) / "runs"),
    "AUTOCOLLAB_MASTER_KEY": "isolated-tests-master-key-not-for-production",
    "SESSION_SECRET": "isolated-tests-session-secret",
    "ANONYMIZED_TELEMETRY": "false",
})

from app.runner import TaskRun


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.run = TaskRun.__new__(TaskRun)
        self.run._stop_requested = False
        self.run._stuck = False
        self.run.publish = Mock()

    def history(self, result=None, errors=(), done=False, success=None):
        return Mock(final_result=Mock(return_value=result), errors=Mock(return_value=list(errors)),
                    is_done=Mock(return_value=done), is_successful=Mock(return_value=success))

    def test_parsing_failure_kept_in_result(self):
        error = self.run._apply_outcome(self.history(errors=["Could not parse response."]))
        self.assertEqual(self.run.status, "echec")
        self.assertEqual(self.run.result, error)
        self.assertIn("format invalide", error)

    def test_success_ignores_recovered_errors(self):
        error = self.run._apply_outcome(self.history("Fichier récupéré", ["Could not parse response."], True, True))
        self.assertEqual(self.run.status, "termine")
        self.assertEqual(self.run.result, "Fichier récupéré")
        self.assertIsNone(error)
        self.run.publish.assert_not_called()

    def test_agent_failure_preserves_specific_result(self):
        error = self.run._apply_outcome(self.history("Document introuvable", ["old error"], True, False))
        self.assertEqual(self.run.status, "echec")
        self.assertEqual(self.run.result, "Document introuvable")
        self.assertIsNone(error)

    def test_step_limit_does_not_blame_recovered_error(self):
        error = self.run._apply_outcome(self.history(errors=["old error", None]))
        self.assertIn("nombre maximal d'étapes", error)

    def test_stop_is_not_failure(self):
        self.run._stop_requested = True
        self.assertIsNone(self.run._apply_outcome(self.history(errors=["old error"])))
        self.assertEqual(self.run.status, "arrete")

    def test_stuck_agent_has_result(self):
        self.run._stuck = True
        self.run._apply_outcome(self.history())
        self.assertEqual(self.run.status, "echec")
        self.assertIn("répétait la même action", self.run.result)


class EventStreamTests(unittest.IsolatedAsyncioTestCase):
    async def read_events(self, status, events):
        from app import main
        run = Mock(status=status, events=events, result=None, finished_at="2026-10-13T12:00:00")
        run.subscribe.return_value = asyncio.Queue()
        with patch.object(main, "_get_run", return_value=run):
            response = await main.task_events("test-run", "test-user")
            async def collect():
                return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]
            result = await asyncio.wait_for(collect(), timeout=1)
        run.unsubscribe.assert_called_once()
        return result

    async def test_interrupted_run_finishes_replay(self):
        events = await self.read_events("interrompu", [{"type": "status", "status": "en_cours"}])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["status"], "interrompu")

    async def test_existing_done_is_not_duplicated(self):
        events = await self.read_events("termine", [{"type": "done", "status": "termine"}])
        self.assertEqual(len(events), 1)


class GuidedSessionTests(unittest.IsolatedAsyncioTestCase):
    """A guided session: the agent waits for the next message; no browser or model involved."""

    def setUp(self):
        self.run = TaskRun.__new__(TaskRun)
        self.run.guided, self.run.status = True, "en_cours"
        self.run.waiting_for_user, self.run._messages, self.run._working = False, None, False
        self.run._stop_requested, self.run._agent, self.run._approval_future = False, None, None
        self.run._work_task = None
        self.run.publish = Mock()

    async def test_stop_cuts_a_hanging_step_short(self):
        self.run._agent = Mock()
        self.run._agent.state.history = "partial history"
        hanging = asyncio.Event()  # never set: a model call or page load that does not return
        work = asyncio.create_task(self.run._work(hanging.wait()))
        await asyncio.sleep(0)
        with patch("app.runner.STOP_GRACE_SECONDS", 0.01):
            await asyncio.to_thread(self.run.request_stop)  # the stop route runs in a request thread
            self.assertEqual(await asyncio.wait_for(work, 1), "partial history")
        self.run._agent.stop.assert_called_once()
        self.assertFalse(self.run._working)

    async def test_message_is_the_next_instruction(self):
        waiting = asyncio.create_task(self.run._next_message())
        await asyncio.sleep(0)
        self.assertTrue(self.run.waiting_for_user)
        self.assertTrue(self.run.send_message("Ouvre le menu Achats", "camille"))
        self.assertEqual(await waiting, "Ouvre le menu Achats")
        self.assertFalse(self.run.waiting_for_user)

    async def test_message_while_working_goes_to_the_agent(self):
        self.run._working, self.run._agent = True, Mock()
        self.assertTrue(self.run.send_message("Plutôt le mois de septembre", "camille"))
        self.run._agent.add_new_task.assert_called_once_with("Plutôt le mois de septembre")

    async def test_finish_and_stop_end_the_wait(self):
        self.assertFalse(self.run.finish_session())  # not waiting yet
        waiting = asyncio.create_task(self.run._next_message())
        await asyncio.sleep(0)
        self.assertTrue(self.run.finish_session())
        self.assertIsNone(await waiting)
        waiting = asyncio.create_task(self.run._next_message())
        await asyncio.sleep(0)
        self.run.request_stop()
        self.assertIsNone(await waiting)

    async def test_idle_session_ends(self):
        with patch("app.runner.config.GUIDED_IDLE_MINUTES", 0.001):
            self.assertIsNone(await self.run._next_message())

    def test_only_a_guided_active_run_takes_messages(self):
        self.run.guided = False
        self.assertFalse(self.run.send_message("Bonjour", "camille"))
        self.run.guided, self.run.status = True, "termine"
        self.assertFalse(self.run.send_message("Bonjour", "camille"))


if __name__ == "__main__":
    unittest.main()
