import type { Metadata } from "next";
import { CommodityExplorer } from "@/widgets/commodity-explorer";

export const metadata: Metadata = {
  title: "Dự báo giá cổ phiếu Việt Nam",
  description:
    "Giá thật + dự báo thống kê (Ridge AR / XGBoost, backtest vs naive) cho rổ VN30 và các cổ phiếu HOSE/HNX/UPCoM được theo dõi.",
};

export default function StocksPage() {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">📈 Cổ phiếu Việt Nam — dự báo giá</h2>
          <p className="text-sm text-muted">
            30 mã blue-chip rổ VN30 của HOSE (kỳ cơ cấu hiệu lực từ 02/02/2026) cùng các mã
            HOSE/HNX/UPCoM khác đang theo dõi. Giá điều chỉnh cập nhật hằng ngày; dự
            báo Ridge AR / XGBoost có backtest so với naive. Mã chưa ingest dữ liệu được đánh dấu{" "}
            <span className="font-medium text-demo">DEMO</span>.
          </p>
          <p className="mt-1 text-xs text-subtle">
            Dự báo là phân tích thống kê trên chuỗi giá lịch sử —{" "}
            <b>không phải lời khuyên đầu tư</b>.
          </p>
        </div>
      </div>
      <CommodityExplorer group="equity" showStats={false} listLabel="Cổ phiếu" />
    </div>
  );
}
