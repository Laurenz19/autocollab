const { test } = require('node:test');
const assert = require('node:assert/strict');
const { describe, stats } = require('../static/run-feedback.js');

test('application inline scripts remain valid JavaScript', () => {
  const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
    new (require('node:vm').Script)(match[1]);
  }
});

test('legacy JSON parsing failures have an actionable explanation', () => {
  const feedback = describe('echec', 'Could not parse response. Return a valid JSON object with the required fields.');
  assert.equal(feedback.title, "Réponse de l'IA invalide");
  assert.match(feedback.advice, /dernières actions/);
});

test('a recovered error never turns a successful run into a failure', () => {
  assert.equal(describe('termine', 'Could not parse response.'), null);
});

test('stops and restarts take priority over older errors', () => {
  assert.equal(describe('interrompu', 'Could not parse response.').title, 'Exécution interrompue');
  assert.equal(describe('arrete', 'Could not parse response.').title, 'Exécution arrêtée');
});

test('unknown errors are not interpreted as instructions or rendered as a title', () => {
  assert.equal(describe('echec', '<script>alert(1)</script>').title, "La tâche n'a pas abouti");
});

test('dashboard explains every finished run and excludes active runs', () => {
  const runs = [...Array(8).fill('termine'), ...Array(7).fill('echec'), 'arrete', 'interrompu', 'arrete',
    'en_cours', 'en_attente', 'a_valider'].map(status => ({ status }));
  assert.deepEqual(stats(runs), { succeeded: 8, failed: 7, other: 3, rate: 44 });
  assert.equal(stats([{ status: 'en_cours' }]).rate, null);
  assert.equal(stats([{ status: 'echec' }]).rate, 0);
});
