/**
 * Ngũ hành (Five Elements) engine for the Kinh Dịch expert — a cultural/novelty
 * layer. Maps a commodity to one of the five elements, computes the year's Can Chi
 * (sexagenary stem-branch), and builds a 12-month favourability cycle from the
 * sinh (generating) / khắc (overcoming) relations. Pure + deterministic.
 */

export type Hanh = "Kim" | "Mộc" | "Thủy" | "Hỏa" | "Thổ";

/** Suggested element per commodity (interpretive — by nature/TCM taste). The AI may refine. */
export const COMMODITY_HANH: Record<string, { hanh: Hanh; reason: string }> = {
  GOLD: { hanh: "Kim", reason: "vàng — kim loại quý, thuộc Kim" },
  COPPER: { hanh: "Kim", reason: "đồng — kim loại, thuộc Kim" },
  CRUDE_OIL: { hanh: "Thủy", reason: "dầu thô — chất lỏng từ lòng đất, tính Thủy (có thể luận Hỏa vì là nhiên liệu)" },
  CORN: { hanh: "Thổ", reason: "ngũ cốc nuôi dưỡng, vị ngọt — thuộc Thổ" },
  WHEAT: { hanh: "Thổ", reason: "lúa mì — ngũ cốc, thuộc Thổ" },
  RICE: { hanh: "Thổ", reason: "lúa gạo — nuôi dưỡng, thuộc Thổ" },
  SOYBEAN: { hanh: "Thổ", reason: "đậu tương — hạt từ đất, thuộc Thổ" },
  PEANUTS: { hanh: "Thổ", reason: "lạc — củ/hạt béo ngọt từ đất, thuộc Thổ" },
  SUGAR: { hanh: "Thổ", reason: "đường — vị ngọt, thuộc Thổ" },
  ROBUSTA: { hanh: "Hỏa", reason: "cà phê — vị đắng, tính kích thích/nóng, thuộc Hỏa" },
  COCOA: { hanh: "Hỏa", reason: "ca cao — vị đắng, thuộc Hỏa" },
  INDIAN_CHILIES: { hanh: "Hỏa", reason: "ớt — cay nóng, thuộc Hỏa" },
  CHINESE_GARLIC: { hanh: "Kim", reason: "tỏi — vị cay (phế), thuộc Kim" },
  DEHYDRATED_GARLIC: { hanh: "Kim", reason: "tỏi sấy — vị cay, thuộc Kim" },
  RED_ONION_INDIA: { hanh: "Kim", reason: "hành — vị cay/hăng, thuộc Kim" },
  RED_ONION_CHINA: { hanh: "Kim", reason: "hành — vị cay, thuộc Kim" },
  DEHYDRATED_ONION: { hanh: "Kim", reason: "hành sấy — vị cay, thuộc Kim" },
  FREIGHT_INDICES: { hanh: "Thủy", reason: "cước vận tải/lưu thông — dòng chảy, thuộc Thủy" },
};

export function hanhOf(code: string | null | undefined): { hanh: Hanh; reason: string } | null {
  return code ? (COMMODITY_HANH[code] ?? null) : null;
}

const CAN = [
  ["Giáp", "Mộc", "Dương"], ["Ất", "Mộc", "Âm"], ["Bính", "Hỏa", "Dương"], ["Đinh", "Hỏa", "Âm"],
  ["Mậu", "Thổ", "Dương"], ["Kỷ", "Thổ", "Âm"], ["Canh", "Kim", "Dương"], ["Tân", "Kim", "Âm"],
  ["Nhâm", "Thủy", "Dương"], ["Quý", "Thủy", "Âm"],
] as const;

const CHI = [
  ["Tý", "Thủy", "Chuột"], ["Sửu", "Thổ", "Trâu"], ["Dần", "Mộc", "Hổ"], ["Mão", "Mộc", "Mèo"],
  ["Thìn", "Thổ", "Rồng"], ["Tỵ", "Hỏa", "Rắn"], ["Ngọ", "Hỏa", "Ngựa"], ["Mùi", "Thổ", "Dê"],
  ["Thân", "Kim", "Khỉ"], ["Dậu", "Kim", "Gà"], ["Tuất", "Thổ", "Chó"], ["Hợi", "Thủy", "Lợn"],
] as const;

export interface CanChi {
  year: number;
  can: string;
  canHanh: Hanh;
  canPolar: string;
  chi: string;
  chiHanh: Hanh;
  conGiap: string;
  label: string;
}

export function yearCanChi(year: number): CanChi {
  const c = CAN[(((year - 4) % 10) + 10) % 10];
  const z = CHI[(((year - 4) % 12) + 12) % 12];
  return {
    year,
    can: c[0],
    canHanh: c[1] as Hanh,
    canPolar: c[2],
    chi: z[0],
    chiHanh: z[1] as Hanh,
    conGiap: z[2],
    label: `${c[0]} ${z[0]} (${z[1]} ${z[2]})`,
  };
}

const SINH: Record<Hanh, Hanh> = { Mộc: "Hỏa", Hỏa: "Thổ", Thổ: "Kim", Kim: "Thủy", Thủy: "Mộc" };
const KHAC: Record<Hanh, Hanh> = { Mộc: "Thổ", Thổ: "Thủy", Thủy: "Hỏa", Hỏa: "Kim", Kim: "Mộc" };

export type Relation = "được sinh" | "đồng hành" | "khắc xuất" | "sinh xuất" | "bị khắc";

/** How the MONTH's element acts on the TARGET (commodity) element. favor: + tốt, − xấu. */
export function relation(month: Hanh, target: Hanh): { rel: Relation; favor: number } {
  if (month === target) return { rel: "đồng hành", favor: 1 };
  if (SINH[month] === target) return { rel: "được sinh", favor: 2 }; // tháng sinh ra hành hàng → vượng
  if (KHAC[month] === target) return { rel: "bị khắc", favor: -2 }; // tháng khắc hành hàng → suy
  if (SINH[target] === month) return { rel: "sinh xuất", favor: -1 }; // hành hàng sinh tháng → hao tổn
  return { rel: "khắc xuất", favor: 1 }; // hành hàng khắc tháng → chủ động, hơi lợi
}

// Tháng âm lịch 1..12 → Địa Chi (tháng Giêng = Dần)
const MONTH_CHI = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1];

export interface MonthCell {
  month: number;
  chi: string;
  hanh: Hanh;
  rel: Relation;
  favor: number;
}

export function monthCycle(target: Hanh): MonthCell[] {
  return MONTH_CHI.map((ci, i) => {
    const z = CHI[ci];
    const r = relation(z[1] as Hanh, target);
    return { month: i + 1, chi: z[0], hanh: z[1] as Hanh, rel: r.rel, favor: r.favor };
  });
}

/** Compact text summary of the favourable/unfavourable months for a prompt. */
export function cycleSummary(target: Hanh): { favorable: string; unfavorable: string } {
  const cells = monthCycle(target);
  const f = cells.filter((c) => c.favor >= 1).map((c) => `T${c.month}(${c.chi})`);
  const u = cells.filter((c) => c.favor < 0).map((c) => `T${c.month}(${c.chi})`);
  return { favorable: f.join(", ") || "—", unfavorable: u.join(", ") || "—" };
}
