const { test } = require('node:test');
const assert = require('node:assert/strict');
const { priorities } = require('../static/dashboard.js');
const now = new Date('2026-10-13T12:00:00Z').getTime();
const run = (id, agent_id, status, day) => ({ id, agent_id, status, created_at: `2026-10-${day}T10:00:00Z` });

test('an agent that succeeded later no longer appears as needing attention', () => {
  assert.deepEqual(priorities([run('failed', 'mail', 'echec', '11'), run('ok', 'mail', 'termine', '12')], now), []);
});
test('keep only latest failure for an agent but retain separate one-off tasks', () => {
  assert.deepEqual(priorities([run('old', 'drive', 'echec', '11'), run('new', 'drive', 'echec', '12'),
    run('task-1', null, 'echec', '12'), run('task-2', null, 'echec', '11')], now).map(r => r.id), ['new', 'task-1', 'task-2']);
});
test('approvals come first even when older than seven days', () => {
  assert.deepEqual(priorities([run('fail', 'drive', 'echec', '12'), run('approval', 'mail', 'a_valider', '02'),
    run('obsolete', 'old', 'echec', '01')], now).map(r => r.id), ['approval', 'fail']);
});
test('a new active attempt replaces the previous failure without mutating history', () => {
  const history = [run('fail', 'drive', 'echec', '11'), run('live', 'drive', 'en_cours', '12')];
  assert.deepEqual(priorities(history, now), []);
  assert.equal(history[0].id, 'fail');
  assert.deepEqual(priorities([], now), []);
});
