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
import { copyToClipboard, promptCopyFallback } from "@/lib/utils/clipboard";
import { ApiClientError } from "@/lib/api/client";
import type { InlineToastVariant } from "@/components/ui/InlineToast";

function KeyRow({
  apiKey,
  onRevoke,
  onNotify,
}: {
  apiKey: KeyResponse;
  onRevoke: (id: number) => void;
  onNotify: (variant: InlineToastVariant, message: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<number>(apiKey.channelId ?? 0);
  const [editError, setEditError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const updateMutation = useUpdateKey();
  const { data: channels } = useActiveChannels();

  const hasRawKey = !!apiKey.rawKey;

  const handleSave = async () => {
    setEditError(null);
    try {
      await updateMutation.mutateAsync({
        id: apiKey.id,
        data: { channelId: selected === 0 ? null : selected },
      });
      setEditing(false);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setEditError(err.message);
      } else {
        setEditError("保存失败，请稍后重试");
      }
    }
  };

  const handleCancel = () => {
    setSelected(apiKey.channelId ?? 0);
    setEditError(null);
    setEditing(false);
  };

  const handleCopy = async () => {
    // 历史 sk 没有明文：bcrypt 不可逆，只能让用户重新创建
    if (!apiKey.rawKey) {
      onNotify(
        "error",
        "该 sk 是历史数据，bcrypt 单向加密不可还原，请撤销后重新创建",
      );
      return;
    }
    let ok = false;
    try {
      ok = await copyToClipboard(apiKey.rawKey);
    } catch {
      ok = false;
    }
    if (ok) {
      setCopied(true);
      onNotify("success", "sk 已复制到剪贴板");
      setTimeout(() => setCopied(false), 3000);
      return;
    }
    // 兜底：弹原生 prompt —— 任何环境都生效
    try {
      promptCopyFallback(apiKey.rawKey);
      setCopied(true);
      onNotify("success", "已打开复制对话框，请使用 Ctrl/⌘+C");
      setTimeout(() => setCopied(false), 3000);
    } catch {
      onNotify("error", "复制失败，请手动选择下方 sk 复制");
    }
  };

  return (
    <div className="rounded-md border border-neutral-border px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-neutral-text-primary truncate">
              {apiKey.name}
            </p>
            <Badge variant={apiKey.status === "active" ? "success" : "error"}>
              {apiKey.status === "active" ? "active" : "revoked"}
            </Badge>
            {!hasRawKey && (
              <Badge variant="warning">
                历史 sk
              </Badge>
            )}
          </div>
        </div>

        {/* 三个按钮在同一水平行 */}
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleCopy}
            data-testid={`copy-key-${apiKey.id}`}
            title={hasRawKey ? "复制完整 sk" : "历史 sk 无明文，需重新创建"}
          >
            {copied ? "已复制" : "复制"}
          </Button>
          {!editing && (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSelected(apiKey.channelId ?? 0);
                  setEditError(null);
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
            </>
          )}
        </div>
      </div>

      {/* sk 明文：select-all，HTTP 下可手动复制 */}
      <div className="mt-2 rounded bg-neutral-bg px-2 py-1.5">
        <code className="block break-all font-mono text-xs text-neutral-text-primary select-all">
          {apiKey.rawKey || maskSK(apiKey.keyPrefix)}
        </code>
      </div>

      <p className="text-xs text-neutral-text-muted mt-1.5">
        prefix {apiKey.keyPrefix} · 创建于 {formatDate(apiKey.createdAt)}
        {apiKey.lastUsedAt && ` · 最后使用 ${formatDate(apiKey.lastUsedAt)}`}
      </p>

      {editing ? (
        <div className="mt-2 flex items-center gap-2">
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
          {editError && (
            <span className="text-xs text-[#dc2626]">{editError}</span>
          )}
        </div>
      ) : (
        <p className="text-xs text-neutral-text-muted mt-1">
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
  );
}

export function KeyList({
  onNotify,
}: {
  onNotify: (variant: InlineToastVariant, message: string) => void;
}) {
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
          <KeyRow
            key={key.id}
            apiKey={key}
            onRevoke={handleRevoke}
            onNotify={onNotify}
          />
        ))
      ) : (
        <p className="text-sm text-neutral-text-secondary">还没有创建 sk</p>
      )}
    </div>
  );
}
