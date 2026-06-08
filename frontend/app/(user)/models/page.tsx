"use client";

import { ChannelExplorer } from "@/components/data/ChannelExplorer";

export default function ModelsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">模型列表</h1>
        <p className="mt-1 text-sm text-neutral-text-secondary">
          浏览可用的渠道与模型
        </p>
      </div>
      <ChannelExplorer />
    </div>
  );
}
