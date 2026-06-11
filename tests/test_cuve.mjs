// Tests du moteur de dimensionnement de cuve (méthode de Rippl).
// Les fonctions sont EXTRAITES de docs/index.html (source unique de vérité),
// pas recopiées : si l'app change, les tests testent la nouvelle version.
//
// Lancer :  node tests/test_cuve.mjs
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'docs/index.html'), 'utf8');

function extract(re, label){
  const m = html.match(re);
  if(!m) throw new Error('Extraction impossible : ' + label);
  return m[0];
}
const src = [
  extract(/const KC = \{[\s\S]*?\n\};/, 'KC'),
  extract(/const KS_ETE = \{[\s\S]*?\n\};/, 'KS_ETE'),
  extract(/const MOIS_ETE = \[.*?\];/, 'MOIS_ETE'),
  extract(/function simulCuve\([\s\S]*?\n\}/, 'simulCuve'),
  extract(/function dimensionne\([\s\S]*?\n\}/, 'dimensionne'),
].join('\n');
const { KC, KS_ETE, MOIS_ETE, simulCuve, dimensionne } =
  new Function(src + '\nreturn { KC, KS_ETE, MOIS_ETE, simulCuve, dimensionne };')();

// même formule que scen() dans l'app (spécification du besoin par culture)
function besoinMensuel(et0, pluie, zones){
  const out = [];
  for(let m=0; m<12; m++){
    let bm = 0;
    for(const z of zones){
      const ke = MOIS_ETE.includes(m) ? (KS_ETE[z.type] || 1) : 1;
      bm += Math.max(0, et0[m]*KC[z.type][m] - pluie[m]) * ke * z.surf / 1000;
    }
    out.push(bm);
  }
  return out;
}
const apportToit = (pluie, surf, coef) => pluie.map(p => p*surf*coef/1000);

let n = 0;
function test(label, fn){ fn(); n++; console.log('  ok —', label); }

// ── invariants de base ────────────────────────────────────────────────
test('besoin nul -> cuve 0, couverture 100 %', () => {
  const r = dimensionne([1,1,1,1,1,1,1,1,1,1,1,1], new Array(12).fill(0));
  assert.equal(r.vol, 0); assert.equal(r.couverture, 1); assert.equal(r.limite, false);
});

test('toit nul -> limité par la toiture', () => {
  const r = dimensionne(new Array(12).fill(0), new Array(12).fill(1));
  assert.equal(r.limite, true);
});

test('couverture croissante avec la capacité', () => {
  const apport = [3,3,2,1,0,0,0,0,1,2,3,3], besoin = [0,0,0,1,2,3,4,3,1,0,0,0];
  let prev = -1;
  for(const cap of [0, 1, 2, 5, 10, 20]){
    const c = simulCuve(cap, apport, besoin).couverture;
    assert.ok(c >= prev - 1e-9, `couverture décroît à cap=${cap}`);
    assert.ok(c >= 0 && c <= 1 + 1e-9);
    prev = c;
  }
});

test('cuve infinie + apport annuel suffisant -> couverture ~100 %', () => {
  const apport = [3,3,2,1,0,0,0,0,1,2,3,3], besoin = [0,0,0,1,2,3,4,3,1,0,0,0];
  const c = simulCuve(1000, apport, besoin).couverture;
  assert.ok(c > 0.999, 'couverture=' + c);
});

test('dimensionne non limité -> couverture >= 99 %', () => {
  const apport = [3,3,2,1,0,0,0,0,1,2,3,3], besoin = [0,0,0,1,2,3,4,3,1,0,0,0];
  const r = dimensionne(apport, besoin);
  assert.equal(r.limite, false);
  assert.ok(r.couverture >= 0.99);
  assert.ok(r.vol > 0 && r.vol < 20);
});

// ── cohérence des tables agronomiques ─────────────────────────────────
test('tables KC/KS_ETE complètes et bornées', () => {
  for(const [type, kc] of Object.entries(KC)){
    assert.equal(kc.length, 12, type);
    kc.forEach(v => assert.ok(v >= 0 && v <= 1.2, type));
    assert.ok(type in KS_ETE, type + ' sans KS_ETE');
    assert.ok(KS_ETE[type] > 0 && KS_ETE[type] <= 1, type);
  }
});

// ── bout-en-bout sur les données réelles d'Ajaccio ────────────────────
test('Ajaccio 100 m² toit / 100 m² oliviers : reco plausible', () => {
  const data = JSON.parse(readFileSync(join(root, 'docs/normales_france.json'), 'utf8'));
  const f = data['11320_16810'].fenetres.ref_1995_2020;
  const zones = [{type:'oliviers', surf:100}];
  const apport = apportToit(f.moy, 100, 0.9);
  const besoin = besoinMensuel(f.et0_moy, f.moy, zones);
  const r = dimensionne(apport, besoin);
  assert.equal(r.limite, false, 'Ajaccio/oliviers ne doit pas être limité toiture');
  assert.ok(r.couverture >= 0.99);
  // ordre de grandeur : quelques m³ (mode survie), pas des dizaines
  assert.ok(r.vol > 0.5 && r.vol < 15, 'reco=' + r.vol.toFixed(1) + ' m³');
  console.log('     (reco Ajaccio oliviers : ' + r.vol.toFixed(1) + ' m³, couverture ' +
              Math.round(r.couverture*100) + ' %)');
});

test('année sèche = mise à l\'échelle du cumul annuel P10 réel', () => {
  const data = JSON.parse(readFileSync(join(root, 'docs/normales_france.json'), 'utf8'));
  const f = data['11320_16810'].fenetres.ref_1995_2020;
  const ratio = f.annee_seche_p10 / f.annuel_moyen;
  assert.ok(ratio > 0 && ratio < 1);
  const pluieSec = f.moy.map(v => v*ratio);
  const cumul = pluieSec.reduce((a,b)=>a+b, 0);
  assert.ok(Math.abs(cumul - f.annee_seche_p10) < 5, 'cumul sec=' + cumul.toFixed(0));
});

console.log(n + ' tests OK');
