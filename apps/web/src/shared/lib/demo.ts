/**
 * Deterministic DEMO price series — clearly synthetic, stable per commodity.
 * Used only to illustrate where real ingested prices will render later; never
 * presented as real data (callers must label it DEMO).
 */

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function demoSeries(code: string, n = 32): number[] {
  const rnd = mulberry32(hashStr(code));
  let v = 40 + rnd() * 60;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    v += (rnd() - 0.48) * v * 0.06;
    out.push(Math.max(1, Math.round(v * 100) / 100));
  }
  return out;
}
