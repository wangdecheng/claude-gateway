"use client";

import { useParams, useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModelDetail } from "@/lib/api/models";
import { formatUnitPrice } from "@/lib/utils/format";

export default function ModelDetailPage() {
  const params = useParams();
  const router = useRouter();
  const rawId = Array.isArray(params.id) ? params.id[0] : params.id;
  const modelId = Number(rawId);
  const isValidModelId = Number.isInteger(modelId) && modelId > 0;
  const { data: model, isLoading, error } = useModelDetail(modelId);

  if (!isValidModelId) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-[#dc2626]">模型不存在或 ID 无效</p>
        <Button variant="secondary" size="sm" onClick={() => router.push("/models")}>
          ← 返回模型列表
        </Button>
      </div>
    );
  }

  if (isLoading) {
    return <p className="text-sm text-neutral-text-secondary">加载中...</p>;
  }

  if (error) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-[#dc2626]">模型不存在或加载失败</p>
        <Button variant="secondary" size="sm" onClick={() => router.push("/models")}>
          ← 返回模型列表
        </Button>
      </div>
    );
  }

  if (!model) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Back + Title */}
      <div>
        <Button variant="ghost" size="sm" onClick={() => router.push("/models")} className="mb-3">
          ← 返回模型列表
        </Button>
        <h1 className="font-mono text-2xl font-bold">{model.publicName}</h1>
        <div className="mt-2 flex items-center gap-3">
          <Badge variant="muted">{model.providerName}</Badge>
          <span className="text-xs text-neutral-text-muted">
            上游 ID: {model.providerModelId}
          </span>
        </div>
      </div>

      {/* Description */}
      {model.description && (
        <Card>
          <CardHeader>
            <CardTitle>模型介绍</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-neutral-text-secondary">{model.description}</p>
          </CardContent>
        </Card>
      )}

      {/* Channels & Pricing */}
      <Card>
        <CardHeader>
          <CardTitle>渠道与定价</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-border text-left text-neutral-text-secondary">
                  <th className="py-2 font-medium">渠道</th>
                  <th className="py-2 font-medium text-right">倍率</th>
                  <th className="py-2 font-medium text-right">输入价格 / 1K</th>
                  <th className="py-2 font-medium text-right">输出价格 / 1K</th>
                </tr>
              </thead>
              <tbody>
                {model.channels.map((ch) => {
                  const inputPrice = model.inputPrice * ch.multiplier;
                  const outputPrice = model.outputPrice * ch.multiplier;
                  return (
                    <tr
                      key={ch.id}
                      className="border-b border-neutral-border last:border-0"
                    >
                      <td className="py-2">
                        <span className="text-neutral-text-primary">
                          {ch.providerName}
                        </span>
                        {ch.isDefault && (
                          <Badge variant="success" className="ml-2">
                            默认
                          </Badge>
                        )}
                      </td>
                      <td className="py-2 text-right font-mono">
                        ×{ch.multiplier}
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatUnitPrice(inputPrice)}
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatUnitPrice(outputPrice)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Market price note */}
          <p className="mt-4 text-xs text-neutral-text-muted">
            市场价：输入 {formatUnitPrice(model.inputPrice)} / 输出{" "}
            {formatUnitPrice(model.outputPrice)} / 1K tokens。实际费用 = 市场价 × 渠道倍率。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
