"use client";

import { useParams } from "next/navigation";
import { Breadcrumb, Card, CardBody } from "@/shared/ui";
import { ProfileDetail } from "@/widgets/profile-detail";

export default function CommodityDetailPage() {
  const params = useParams<{ code: string }>();
  const code = decodeURIComponent(params.code ?? "").toUpperCase();

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: "Explorer", href: "/" }, { label: "Commodities", href: "/" }, { label: code }]} />
      <Card>
        <CardBody>
          <ProfileDetail code={code} />
        </CardBody>
      </Card>
    </div>
  );
}
