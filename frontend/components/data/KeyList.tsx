"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  useKeys,
  useRevokeKey,
  useUpdateKey,
  type KeyResponse,
} from "@/lib/api/keys";
import { useActiveChannels } from "@/lib/api/channels";
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
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<number>(apiKey.channelId ?? 0);
  const [error, setError] = useState<string | null>(null);

  const updateMutation = useUpdateKey();
  const { data: channels } = useActiveChannels();

  const handleSave = async () => {
    setError(null);
    try {
      await updateMutation.mutateAsync({
        id: apiKey.id,
        data: { channelId: selected === 0 ? null : selected },
      });
      setEditing(false);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("保存失败，请稍后重试");
      }
    }
  };

  const handleCancel = () => {
    setSelected(apiKey.channelId ?? 0);
    setError(null);
    setEditing(false);
  };

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

          {editing ? (
            <div className="mt-1.5 flex items-center gap-2">
              <select
                value={selected}
                onChange={(e) => setSelected(Number(e.target.value))}
                className="rounded-md border border-neutral-border bg-neutral-surface px-2 py-1 text-xs text-neutral-text-primary focus:outline-none focus:ring-2 focus:ring-primary-subtle"
              >
                <option value={0}>自动（按模型默认）</option>
                {channels?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.channelName} ({c.multiplier}x)
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="primary"
                onClick={handleSave}
                disabled={updateMutation.isPending}
              >
                {updateMutation.isPending ? "保存中..." : "保存"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={handleCancel}
                disabled={updateMutation.isPending}
              >
                取消
              </Button>
              {error && (
                <span className="text-xs text-[#dc2626]">{error}</span>
              )}
            </div>
          ) : (
            <p className="text-xs text-neutral-text-muted mt-0.5">
              {apiKey.channelName ? (
                <>
                  绑定渠道：{" "}
                  <span className="font-mono text-neutral-text-primary">
                    {apiKey.channelName}
                  </span>
                </>
              ) : (
                <>自动（按模型默认）</>
              )}
            </p>
          )}
        </div>
      </div>

      {!editing && (
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSelected(apiKey.channelId ?? 0);
              setError(null);
              setEditing(true);
            }}
          >
            编辑
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onRevoke(apiKey.id)}
            className="text-[#dc2626] hover:bg-[#fef2f2]"
          >
            撤销
          </Button>
        </div>
      )}
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
        keys.map((key) => (
          <KeyRow key={key.id} apiKey={key} onRevoke={handleRevoke} />
        ))
      ) : (
        <p className="text-sm text-neutral-text-secondary">还没有创建 sk</p>
      )}
    </div>
  );
}
