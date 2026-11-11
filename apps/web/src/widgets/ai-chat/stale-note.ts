// A series that stopped updating still forecasts cleanly; the model must be told the
// anchor is old, or it will present a months-old price as the current market.
export function staleDataNote(d: {
  last_date?: string;
  data_age_days?: number | null;
  data_stale?: boolean | null;
}): string {
  if (!d.data_stale) return "";
  const age = d.data_age_days != null ? ` (${d.data_age_days} ngày trước)` : "";
  return (
    ` CẢNH BÁO: chuỗi giá đã ngừng cập nhật từ ${d.last_date ?? "?"}${age}; "giá cuối" và dự báo neo trên mức giá cũ, ` +
    "KHÔNG phải giá thị trường hiện tại. Hãy nói rõ điều này với người dùng."
  );
}
