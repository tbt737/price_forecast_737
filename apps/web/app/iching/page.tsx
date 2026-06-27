import type { Metadata } from "next";
import { IchingExpert } from "@/widgets/iching";

export const metadata: Metadata = {
  title: "Chuyên gia Kinh Dịch & Ngũ hành",
  description: "Hỏi chuyên gia AI luận giá theo Kinh Dịch + Ngũ hành — văn hoá/giải trí, không phải dự báo của model.",
};

export default function IchingPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-text">🔮 Chuyên gia Kinh Dịch &amp; Ngũ hành</h1>
        <p className="text-sm text-muted">
          Chọn hàng hóa, viết câu hỏi → app gieo quẻ Kinh Dịch + quy ngũ hành (Can Chi năm, chu kỳ tháng) rồi nhờ AI
          luận giải như một thầy Dịch. Vui là chính — không phải dự báo của model định lượng, không phải lời khuyên đầu
          tư.
        </p>
      </div>
      <IchingExpert />
    </div>
  );
}
