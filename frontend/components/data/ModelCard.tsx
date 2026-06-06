"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatUnitPrice } from "@/lib/utils/format";
import type { ModelWithChannels, ChannelInfo } from "@/lib/api/models";

interface ModelCardProps {
  model: ModelWithChannels;
}

function ChannelSelect({
  channels,
  selectedId,
  onChange,
}: {
  channels: ChannelInfo[];
  selectedId: number;
  onChange: (id: number) => void;
}) {
  return (
    <select
      value={selectedId}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full rounded-sm border border-neutral-border bg-neutral-surface px-2 py-1 text-xs text-neutral-text-primary focus:outline-none focus:ring-2 focus:ring-primary-subtle"
    >
      {channels.map((ch) => (
        <option key={ch.id} value={ch.id}>
          {ch.providerName}{" "}
          {ch.isDefault ? `(默认 ×${ch.multiplier})` : `(×${ch.multiplier})`}
        </option>
      ))}
    </select>
  );
}

export function ModelCard({ model }: ModelCardProps) {
  const router = useRouter();

  // Find default channel
  const defaultChannel = useMemo(
    () => model.channels.find((c) => c.isDefault) ?? model.channels[0],
    [model.channels]
  );

  const [selectedChannelId, setSelectedChannelId] = useState<number>(
    defaultChannel?.id ?? 0
  );

  const selectedChannel = useMemo(
    () => model.channels.find((c) => c.id === selectedChannelId),
    [model.channels, selectedChannelId]
  );

  const estimatedOutputPrice = selectedChannel
    ? model.outputPrice * selectedChannel.multiplier
    : model.outputPrice;

  const estimatedInputPrice = selectedChannel
    ? model.inputPrice * selectedChannel.multiplier
    : model.inputPrice;

  const handleClick = () => {
    router.push(`/models/${model.id}`);
  };

  return (
    <Card hoverable className="cursor-pointer" onClick={handleClick}>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="font-mono text-base">{model.publicName}</CardTitle>
          {model.channels.length > 1 && (
            <Badge variant="muted">{model.channels.length} 渠道</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Description */}
        {model.description && (
          <p className="line-clamp-2 text-sm text-neutral-text-secondary">
            {model.description}
          </p>
        )}

        {/* Channel Selector */}
        {model.channels.length > 0 && (
          <div className="space-y-1" onClick={(e) => e.stopPropagation()}>
            <span className="text-xs text-neutral-text-muted">渠道</span>
            <ChannelSelect
              channels={model.channels}
              selectedId={selectedChannelId}
              onChange={setSelectedChannelId}
            />
          </div>
        )}

        {/* Estimated Price */}
        {selectedChannel && (
          <div className="rounded-sm bg-neutral-bg px-3 py-2">
            <p className="text-xs text-neutral-text-muted">
              预估价格 / 1K tokens
            </p>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-mono text-sm text-neutral-text-primary">
                输入 {formatUnitPrice(estimatedInputPrice)}
              </span>
              <span className="font-mono text-sm text-neutral-text-primary">
                输出 {formatUnitPrice(estimatedOutputPrice)}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
