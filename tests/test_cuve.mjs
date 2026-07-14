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
  extract(/const JOURS_MOIS = \[.*?\];/, 'JOURS_MOIS'),
  extract(/const MAX_SELECTION_KM = .*?;/, 'MAX_SELECTION_KM'),
  extract(/function haversine\([\s\S]*?\n\}/, 'haversine'),
  extract(/function findMaille\([\s\S]*?\n\}/, 'findMaille'),
  extract(/function demandeDomestique\([\s\S]*?\n\}/, 'demandeDomestique'),
  extract(/function simulCuve\([\s\S]*?\n\}/, 'simulCuve'),
  extract(/function besoinCultureMensuel\([\s\S]*?\n\}/, 'besoinCultureMensuel'),
  extract(/function dimensionne\([\s\S]*?\n\}/, 'dimensionne'),
].join('\n');
const { KC, KS_ETE, MOIS_ETE, JOURS_MOIS, MAX_SELECTION_KM, haversine, findMaille,
        demandeDomestique, simulCuve, besoinCultureMensuel, dimensionne } =
  new Function(src + '\nreturn { KC, KS_ETE, MOIS_ETE, JOURS_MOIS, MAX_SELECTION_KM, haversine, findMaille, demandeDomestique, simulCuve, besoinCultureMensuel, dimensionne };')();

// même formule que scen() dans l'app (spécification du besoin par culture)
function besoinMensuel(et0, pluie, zones){
  const out = [];
  for(let m=0; m<12; m++){
    let bm = 0;
    for(const z of zones){
      bm += besoinCultureMensuel(et0[m], pluie[m], {
        kc: KC[z.type], ksEte: KS_ETE[z.type], surf: z.surf
      }, m);
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

test('apport annuel insuffisant -> pas de couverture financée par le stock initial', () => {
  const apport = new Array(12).fill(98/12);
  const besoin = new Array(12).fill(100/12);
  const r = dimensionne(apport, besoin);
  assert.equal(r.limite, true);
  assert.ok(r.couverture <= 0.981, 'couverture=' + r.couverture);
  assert.ok(simulCuve(20, apport, besoin).couverture <= 0.981);
});

test('livraison et couverture restent cohérentes', () => {
  const r = simulCuve(5, [3,3,2,1,0,0,0,0,1,2,3,3], [0,0,0,1,2,3,4,3,1,0,0,0]);
  assert.ok(r.demande > 0);
  assert.ok(Math.abs(r.livre/r.demande - r.couverture) < 1e-12);
});

test('sélection spatiale : commune privilégiée et garde hors zone', () => {
  const mailles = [
    {id:'mer', lat:42, lon:9, data:{commune:null}},
    {id:'terre', lat:42.01, lon:9, data:{commune:'Test'}}
  ];
  const r = findMaille(42, 9, mailles);
  assert.equal(r.maille.id, 'terre');
  assert.ok(r.dist < MAX_SELECTION_KM);
  assert.ok(haversine(42, 9, 43, 9) > MAX_SELECTION_KM);
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

test('survie estivale = fraction du déficit complet, après déduction de la pluie', () => {
  const zone = {kc: KC.oliviers, ksEte: KS_ETE.oliviers, surf: 100};
  const m = 6, et0 = 150, pluie = 20;
  const attendu = Math.max(0, et0*zone.kc[m] - pluie) * zone.ksEte * zone.surf / 1000;
  const ancienneForme = Math.max(0, et0*zone.kc[m]*zone.ksEte - pluie) * zone.surf / 1000;
  assert.ok(Math.abs(besoinCultureMensuel(et0, pluie, zone, m) - attendu) < 1e-12);
  assert.notEqual(attendu, ancienneForme);
});

// ── usage domestique (WC + lave-linge) ────────────────────────────────
test('demandeDomestique : constante, prorata des jours, échelle occupants', () => {
  const occup = 4, lpj = 42;              // 25 (WC) + 17 (lave-linge) L/pers/jour
  const d = demandeDomestique(occup, lpj);
  assert.equal(d.length, 12);
  // somme annuelle ≈ occupants × lpj × 365 / 1000
  const ann = d.reduce((a,b)=>a+b, 0);
  assert.ok(Math.abs(ann - occup*lpj*365/1000) < 1e-9, 'annuel=' + ann.toFixed(2));
  // chaque mois = prorata des jours (janvier 31 j > février 28 j)
  assert.ok(d[0] > d[1], 'janvier doit dépasser février');
  assert.ok(Math.abs(d[0] - occup*lpj*31/1000) < 1e-9);
  // proportionnel au nb d'occupants
  const d8 = demandeDomestique(8, lpj);
  assert.ok(Math.abs(d8[0] - 2*d[0]) < 1e-9, 'doublé pour 2× occupants');
  // entrées négatives bornées à 0
  assert.equal(demandeDomestique(-3, lpj)[0], 0);
});

test('demande domestique identique en année normale et sèche', () => {
  const normale = demandeDomestique(4, 42);
  const seche = demandeDomestique(4, 42);
  assert.deepEqual(seche, normale);
});

test('cuve mixte : le domestique augmente reco ET besoin vs jardin seul', () => {
  const data = JSON.parse(readFileSync(join(root, 'docs/normales_france.json'), 'utf8'));
  const f = data['11320_16810'].fenetres.ref_1995_2020;
  const zones = [{type:'gazon_chaud', surf:50}];
  const apport = apportToit(f.moy, 100, 0.9);
  const besoinJardin = besoinMensuel(f.et0_moy, f.moy, zones);
  const dom = demandeDomestique(4, 42);                 // 4 pers, WC + lave-linge
  const besoinMixte = besoinJardin.map((b,i) => b + dom[i]);
  const rJardin = dimensionne(apport, besoinJardin);
  const rMixte  = dimensionne(apport, besoinMixte);
  // le besoin domestique constant s'ajoute -> reco mixte >= reco jardin seul
  assert.ok(rMixte.vol >= rJardin.vol, 'reco mixte ' + rMixte.vol.toFixed(1) +
            ' < jardin ' + rJardin.vol.toFixed(1));
  // le besoin annuel mixte dépasse le jardin seul d'environ la demande domestique
  const annJardin = besoinJardin.reduce((a,b)=>a+b,0);
  const annMixte  = besoinMixte.reduce((a,b)=>a+b,0);
  assert.ok(Math.abs((annMixte - annJardin) - dom.reduce((a,b)=>a+b,0)) < 1e-9);
  console.log('     (reco jardin ' + rJardin.vol.toFixed(1) + ' m³ → mixte ' +
              rMixte.vol.toFixed(1) + ' m³, couverture ' + Math.round(rMixte.couverture*100) + ' %)');
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
