import type { Metadata } from "next";
import { IchingOracle } from "@/widgets/iching";

export const metadata: Metadata = {
  title: "Gieo quẻ Kinh Dịch",
  description: "Gieo quẻ Kinh Dịch — module văn hoá/giải trí, không phải dự báo của model.",
};

export default function IchingPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-text">🔮 Gieo quẻ Kinh Dịch</h1>
        <p className="text-sm text-muted">
          Gieo một quẻ cho thị trường (tung 6 hào kiểu 3 đồng xu) — vui là chính, không phải dự báo của model định
          lượng và không phải lời khuyên đầu tư.
        </p>
      </div>
      <IchingOracle commodityName="thị trường" />
    </div>
  );
}
