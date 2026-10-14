/* Dashboard selection rules: keep actionable runs ahead of historical noise. */
(function (root) {
  function priorities(runs, now = Date.now()) {
    const sorted = [...runs].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const latest = new Map();
    for (const run of sorted) {
      const key = run.agent_id ? `agent:${run.agent_id}` : `task:${run.id}`;
      if (!latest.has(key)) latest.set(key, run);
    }
    const approvals = sorted.filter(r => r.status === "a_valider").reverse();
    const failures = [...latest.values()].filter(r => r.status === "echec" && now - new Date(r.created_at) <= 7 * 864e5);
    return [...approvals, ...failures];
  }
  const api = { priorities };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Dashboard = api;
})(typeof window !== "undefined" ? window : globalThis);
