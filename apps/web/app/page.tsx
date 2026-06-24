import { CommodityExplorer } from "@/widgets/commodity-explorer";

export default function HomePage() {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Commodity Explorer</h2>
          <p className="text-sm text-muted">
            18 hồ sơ hàng hóa cấu hình-hoá. Phần lớn đã có giá thật + dự báo (Ridge AR / XGBoost, có
            backtest vs naive); mặt hàng chưa có nguồn dữ liệu được đánh dấu{" "}
            <span className="font-medium text-demo">DEMO</span>.
          </p>
        </div>
      </div>
      <CommodityExplorer />
    </div>
  );
}
