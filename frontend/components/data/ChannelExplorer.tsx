"use client";

import { useState } from "react";
import { useActiveChannels, useChannelModels } from "@/lib/api/channels";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatUnitPrice } from "@/lib/utils/format";

export function ChannelExplorer() {
  const { data: channels, isLoading, error } = useActiveChannels();
  const [selectedId, setSelectedId] = useState<number>(0);

  // Auto-select first channel once loaded.
  const effectiveId = selectedId > 0 ? selectedId : channels?.[0]?.id ?? 0;
  const { data: detail, isLoading: detailLoading } = useChannelModels(effectiveId);

  if (isLoading) {
    return (
      <p className="text-sm text-neutral-text-secondary">加载中...</p>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-[#dc2626]">加载失败，请刷新重试</p>
    );
  }

  if (!channels || channels.length === 0) {
    return (
      <div className="rounded-md border border-neutral-border bg-neutral-surface p-8 text-center">
        <p className="text-sm text-neutral-text-secondary">暂无可用的渠道</p>
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <div className="space-y-2">
        <h2 className="text-sm font-medium text-neutral-text-secondary px-1">
          可用渠道
        </h2>
        {channels.map((c) => {
          const isSelected = effectiveId === c.id;
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => setSelectedId(c.id)}
              className={[
                "w-full text-left rounded-md border px-4 py-3 transition-colors",
                isSelected
                  ? "border-primary-base bg-primary-subtle"
                  : "border-neutral-border bg-neutral-surface hover:bg-neutral-bg",
              ].join(" ")}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-neutral-text-primary">
                  {c.channelName}
                </span>
                <Badge variant="muted">{c.multiplier}x</Badge>
              </div>
            </button>
          );
        })}
      </div>

      <Card>
        <CardContent className="space-y-4">
          {detail && (
            <div className="rounded-md bg-primary-subtle border border-primary-light px-4 py-2">
              <p className="text-sm font-medium text-primary-base">
                {detail.channel.channelName}
              </p>
            </div>
          )}

          {detailLoading && (
            <p className="text-sm text-neutral-text-secondary">加载模型中...</p>
          )}

          {detail && detail.models.length === 0 && (
            <p className="text-sm text-neutral-text-secondary">
              该渠道暂无可用模型
            </p>
          )}

          {detail && detail.models.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-neutral-text-muted">
                  <th className="py-2">模型</th>
                  <th className="py-2">输入价格</th>
                  <th className="py-2">输出价格</th>
                </tr>
              </thead>
              <tbody>
                {detail.models.map((m) => (
                  <tr key={m.id} className="border-t border-neutral-border">
                    <td className="py-2 font-mono">{m.publicName}</td>
                    <td className="py-2 font-mono">
                      {formatUnitPrice(m.inputPrice)}
                    </td>
                    <td className="py-2 font-mono">
                      {formatUnitPrice(m.outputPrice)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
