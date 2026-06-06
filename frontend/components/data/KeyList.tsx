"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useKeys, useRevokeKey, type KeyResponse } from "@/lib/api/keys";
import { maskSK } from "@/lib/utils/mask";
import { formatDate } from "@/lib/utils/format";
import { ApiClientError } from "@/lib/api/client";

function KeyRow({
  apiKey,
  onRevoke,
}: {
  apiKey: KeyResponse;
  onRevoke: (id: number) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border border-neutral-border px-4 py-3">
      <div className="flex items-center gap-4 min-w-0">
        <div className="min-w-0">
          <p className="text-sm font-medium text-neutral-text-primary truncate">
            {apiKey.name}
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            <code className="text-xs font-mono text-neutral-text-secondary">
              {maskSK(apiKey.keyPrefix)}
            </code>
            <Badge variant={apiKey.status === "active" ? "success" : "error"}>
              {apiKey.status === "active" ? "active" : "revoked"}
            </Badge>
          </div>
          <p className="text-xs text-neutral-text-muted mt-0.5">
            创建于 {formatDate(apiKey.createdAt)}
            {apiKey.lastUsedAt && ` · 最后使用 ${formatDate(apiKey.lastUsedAt)}`}
          </p>
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => onRevoke(apiKey.id)}
        className="shrink-0 text-[#dc2626] hover:bg-[#fef2f2]"
      >
        撤销
      </Button>
    </div>
  );
}

export function KeyList() {
  const { data: keys, isLoading } = useKeys();
  const revokeMutation = useRevokeKey();
  const [error, setError] = useState<string | null>(null);

  const handleRevoke = async (keyId: number) => {
    try {
      setError(null);
      await revokeMutation.mutateAsync(keyId);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("撤销失败，请稍后重试");
      }
    }
  };

  if (isLoading) {
    return <p className="text-sm text-neutral-text-secondary">加载中...</p>;
  }

  return (
    <div className="space-y-3">
      {error && <p className="text-sm text-[#dc2626]">{error}</p>}
      {keys && keys.length > 0 ? (
        keys.map((key) => <KeyRow key={key.id} apiKey={key} onRevoke={handleRevoke} />)
      ) : (
        <p className="text-sm text-neutral-text-secondary">还没有创建 sk</p>
      )}
    </div>
  );
}
