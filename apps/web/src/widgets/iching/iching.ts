/**
 * Kinh Dịch (I Ching) oracle — a NOVELTY / cultural module, not a forecast.
 *
 * Casts six lines by the three-coin method, builds the primary hexagram (one of
 * the 64), derives any "changing lines" (lão âm/lão dương) into a resulting
 * hexagram, and maps the trigrams to a light-hearted "thiên hướng giá". Pure +
 * deterministic given its line input, so the mapping is unit-testable. The market
 * lean is for fun only — see the disclaimer in the widget.
 */

// 8 trigrams (bát quái), indexed by bits = line1 + 2*line2 + 4*line3 (bottom→top).
export interface Trigram {
  name: string; // Hán-Việt
  nature: string; // tượng (Thiên/Địa/…)
  symbol: string; // unicode trigram
  lean: number; // market-flavour weight (fun): + = dương/tăng, − = âm/giảm
}

export const TRIGRAMS: Trigram[] = [
  { name: "Khôn", nature: "Địa", symbol: "☷", lean: -1 }, // 0  000
  { name: "Chấn", nature: "Lôi", symbol: "☳", lean: +2 }, // 1  100
  { name: "Khảm", nature: "Thủy", symbol: "☵", lean: -2 }, // 2  010
  { name: "Đoài", nature: "Trạch", symbol: "☱", lean: 0 }, // 3  110
  { name: "Cấn", nature: "Sơn", symbol: "☶", lean: -1 }, // 4  001
  { name: "Ly", nature: "Hỏa", symbol: "☲", lean: +1 }, // 5  101
  { name: "Tốn", nature: "Phong", symbol: "☴", lean: +1 }, // 6  011
  { name: "Càn", nature: "Thiên", symbol: "☰", lean: +2 }, // 7  111
];

// 64 hexagram names keyed by the 6-bit pattern l1l2l3l4l5l6 (1=hào dương, bottom→top;
// lower trigram = l1l2l3, upper = l4l5l6).
export const HEX_NAMES: Record<string, string> = {
  "111111": "Thuần Càn", "000000": "Thuần Khôn", "100010": "Truân", "010001": "Mông",
  "111010": "Nhu", "010111": "Tụng", "010000": "Sư", "000010": "Tỷ",
  "111011": "Tiểu Súc", "110111": "Lý", "111000": "Thái", "000111": "Bĩ",
  "101111": "Đồng Nhân", "111101": "Đại Hữu", "001000": "Khiêm", "000100": "Dự",
  "100110": "Tùy", "011001": "Cổ", "110000": "Lâm", "000011": "Quán",
  "100101": "Phệ Hạp", "101001": "Bí", "000001": "Bác", "100000": "Phục",
  "100111": "Vô Vọng", "111001": "Đại Súc", "100001": "Di", "011110": "Đại Quá",
  "010010": "Tập Khảm", "101101": "Thuần Ly", "001110": "Hàm", "011100": "Hằng",
  "001111": "Độn", "111100": "Đại Tráng", "000101": "Tấn", "101000": "Minh Di",
  "101011": "Gia Nhân", "110101": "Khuê", "001010": "Kiển", "010100": "Giải",
  "110001": "Tổn", "100011": "Ích", "111110": "Quải", "011111": "Cấu",
  "000110": "Tụy", "011000": "Thăng", "010110": "Khốn", "011010": "Tỉnh",
  "101110": "Cách", "011101": "Đỉnh", "100100": "Thuần Chấn", "001001": "Thuần Cấn",
  "001011": "Tiệm", "110100": "Quy Muội", "101100": "Phong", "001101": "Lữ",
  "011011": "Thuần Tốn", "110110": "Thuần Đoài", "010011": "Hoán", "110010": "Tiết",
  "110011": "Trung Phu", "001100": "Tiểu Quá", "101010": "Ký Tế", "010101": "Vị Tế",
};

export interface Line {
  yang: boolean; // ⚊ dương / ⚋ âm
  changing: boolean; // lão âm (6) or lão dương (9) → biến hào
}

export interface Hexagram {
  bits: string; // l1l2l3l4l5l6
  name: string;
  lower: Trigram;
  upper: Trigram;
  yangCount: number;
}

export interface MarketLean {
  label: string; // Tăng mạnh / Tăng / Đi ngang / Giảm / Giảm mạnh
  tone: "up" | "down" | "flat";
}

function trigramOf(b: [boolean, boolean, boolean]): Trigram {
  return TRIGRAMS[(b[0] ? 1 : 0) + (b[1] ? 2 : 0) + (b[2] ? 4 : 0)];
}

/** Build a hexagram record from six lines (bottom→top). */
export function hexagramOf(lines: Line[]): Hexagram {
  const bits = lines.map((l) => (l.yang ? "1" : "0")).join("");
  const lower = trigramOf([lines[0].yang, lines[1].yang, lines[2].yang]);
  const upper = trigramOf([lines[3].yang, lines[4].yang, lines[5].yang]);
  return {
    bits,
    name: HEX_NAMES[bits] ?? `${upper.nature} ${lower.nature}`,
    lower,
    upper,
    yangCount: lines.filter((l) => l.yang).length,
  };
}

/** Fun "thiên hướng giá" from trigram natures + yang balance (NOT a forecast). */
export function leanOf(hex: Hexagram): MarketLean {
  const score = hex.upper.lean + hex.lower.lean + (hex.yangCount - 3) * 0.5;
  if (score >= 2) return { label: "Thiên hướng TĂNG mạnh", tone: "up" };
  if (score >= 0.5) return { label: "Thiên hướng tăng", tone: "up" };
  if (score > -0.5) return { label: "Đi ngang / giằng co", tone: "flat" };
  if (score > -2) return { label: "Thiên hướng giảm", tone: "down" };
  return { label: "Thiên hướng GIẢM mạnh", tone: "down" };
}

/** One line via the three-coin method: 6 lão âm, 7 thiếu dương, 8 thiếu âm, 9 lão dương. */
function castLine(rand: () => number): Line {
  const sum = [0, 0, 0].reduce((s) => s + (rand() < 0.5 ? 3 : 2), 0); // 6..9
  return { yang: sum === 7 || sum === 9, changing: sum === 6 || sum === 9 };
}

export interface Reading {
  lines: Line[]; // bottom→top
  primary: Hexagram;
  changed: Hexagram | null; // biến quẻ if any changing lines
  changingIndices: number[]; // 0-based, bottom→top
  primaryLean: MarketLean;
  changedLean: MarketLean | null;
}

/** Cast a full reading. ``rand`` defaults to Math.random (injectable for tests). */
export function castReading(rand: () => number = Math.random): Reading {
  const lines = Array.from({ length: 6 }, () => castLine(rand));
  const primary = hexagramOf(lines);
  const changingIndices = lines.map((l, i) => (l.changing ? i : -1)).filter((i) => i >= 0);
  let changed: Hexagram | null = null;
  if (changingIndices.length > 0) {
    const flipped = lines.map((l) => ({ yang: l.changing ? !l.yang : l.yang, changing: false }));
    changed = hexagramOf(flipped);
  }
  return {
    lines,
    primary,
    changed,
    changingIndices,
    primaryLean: leanOf(primary),
    changedLean: changed ? leanOf(changed) : null,
  };
}
