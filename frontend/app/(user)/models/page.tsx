"use client";

import { useModels } from "@/lib/api/models";
import { ModelCard } from "@/components/data/ModelCard";

export default function ModelsPage() {
  const { data: models, isLoading, error } = useModels();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">模型列表</h1>
        <p className="mt-1 text-sm text-neutral-text-secondary">
          浏览平台支持的 AI 模型，查看渠道和预估价格
        </p>
      </div>

      {isLoading && (
        <p className="text-sm text-neutral-text-secondary">加载中...</p>
      )}

      {error && (
        <p className="text-sm text-[#dc2626]">
          加载模型列表失败，请刷新重试
        </p>
      )}

      {models && models.length === 0 && (
        <div className="rounded-md border border-neutral-border bg-neutral-surface p-8 text-center">
          <p className="text-sm text-neutral-text-secondary">
            暂无可用的模型
          </p>
          <p className="mt-1 text-xs text-neutral-text-muted">
            管理员上架模型后将在此显示
          </p>
        </div>
      )}

      {models && models.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {models.map((model) => (
            <ModelCard key={model.id} model={model} />
          ))}
        </div>
      )}
    </div>
  );
}
