"use client";

import { useState } from "react";
import { Copy, Ticket } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineToast, type InlineToastVariant } from "@/components/ui/InlineToast";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiClientError } from "@/lib/api/client";
import {
  useAdminRedemptionList,
  useCreateAdminRedemptionCode,
  type AdminRedemptionCreateResult,
  type AdminRedemptionListItem,
} from "@/lib/api/admin/redemption";
import { copyToClipboard } from "@/lib/utils/clipboard";
import { formatDate, formatPrice } from "@/lib/utils/format";

interface ToastState {
  variant: InlineToastVariant;
  message: string;
  /** Bumped on every show so an identical consecutive copy still re-fires. */
  key: number;
}

const STATUS_META: Record<string, { label: string; variant: BadgeVariant }> = {
  issued: { label: "未使用", variant: "success" },
  used: { label: "已使用", variant: "muted" },
  expired: { label: "已过期", variant: "error" },
};

function statusBadge(status: string) {
  const meta = STATUS_META[status] ?? { label: status, variant: "muted" as BadgeVariant };
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}

export default function AdminRedemptionPage() {
  const createMutation = useCreateAdminRedemptionCode();
  const listQuery = useAdminRedemptionList();
  const [amountYuan, setAmountYuan] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("5");
  const [result, setResult] = useState<AdminRedemptionCreateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setCopied(false);

    const amount = Math.round(Number(amountYuan) * 100);
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("请输入大于 0 的金额");
      return;
    }

    const validDays = Number(expiresInDays);
    if (!Number.isInteger(validDays) || validDays <= 0) {
      setError("有效天数必须为正整数");
      return;
    }

    try {
      const data = await createMutation.mutateAsync({
        amount,
        expiresInDays: validDays,
      });
      setResult(data);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("生成失败，请重试");
      }
    }
  };

  const handleCopy = async () => {
    if (!result) return;
    const ok = await copyToClipboard(result.code);
    if (ok) {
      setCopied(true);
      setToast({
        variant: "success",
        message: "兑换码已复制到剪贴板",
        key: Date.now(),
      });
      setTimeout(() => setCopied(false), 2000);
    } else {
      setToast({
        variant: "error",
        message: "复制失败，请手动选择上方兑换码复制",
        key: Date.now(),
      });
    }
  };

  const items: AdminRedemptionListItem[] = listQuery.data ?? [];

  return (
    <div className="space-y-6">
      <InlineToast
        open={toast !== null}
        variant={toast?.variant ?? "success"}
        message={toast?.message ?? ""}
        onClose={() => setToast(null)}
      />

      <div>
        <h1 className="text-2xl font-semibold text-neutral-text-primary">
          兑换码管理
        </h1>
        <p className="mt-1 text-sm text-neutral-text-secondary">
          生成一次性余额兑换码，完整兑换码只在生成后显示一次
        </p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <form onSubmit={handleSubmit} className="grid gap-5 md:grid-cols-[1fr_180px_auto]">
          <div className="space-y-2">
            <Label htmlFor="amount">金额</Label>
            <Input
              id="amount"
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              value={amountYuan}
              onChange={(event) => setAmountYuan(event.target.value)}
              placeholder="例如 10.00"
              disabled={createMutation.isPending}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="expiresInDays">有效天数</Label>
            <Input
              id="expiresInDays"
              type="number"
              min="1"
              step="1"
              value={expiresInDays}
              onChange={(event) => setExpiresInDays(event.target.value)}
              disabled={createMutation.isPending}
            />
          </div>

          <div className="flex items-end">
            <Button type="submit" disabled={createMutation.isPending}>
              <Ticket className="h-4 w-4" />
              {createMutation.isPending ? "生成中..." : "生成兑换码"}
            </Button>
          </div>
        </form>

        {error && (
          <div className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-600" role="alert">
            {error}
          </div>
        )}
      </div>

      {result && (
        <div className="rounded-lg border border-slate-200 bg-white p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-neutral-text-primary">
                生成成功
              </h2>
              <p className="mt-1 text-sm text-neutral-text-secondary">
                请现在复制并交给用户，后台不会再次显示完整兑换码
              </p>
            </div>
            <Button variant="secondary" onClick={handleCopy}>
              <Copy className="h-4 w-4" />
              {copied ? "已复制" : "复制兑换码"}
            </Button>
          </div>

          <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-4">
            <div className="break-all font-mono text-lg font-semibold tracking-wide text-neutral-text-primary select-all">
              {result.code}
            </div>
          </div>

          <dl className="mt-5 grid gap-4 text-sm md:grid-cols-3">
            <div>
              <dt className="text-neutral-text-secondary">金额</dt>
              <dd className="mt-1 font-medium text-neutral-text-primary">
                {formatPrice(result.amount)}
              </dd>
            </div>
            <div>
              <dt className="text-neutral-text-secondary">状态</dt>
              <dd className="mt-1 font-medium text-neutral-text-primary">
                {result.status === "issued" ? "未使用" : result.status}
              </dd>
            </div>
            <div>
              <dt className="text-neutral-text-secondary">过期时间</dt>
              <dd className="mt-1 font-medium text-neutral-text-primary">
                {formatDate(result.expiresAt)}
              </dd>
            </div>
          </dl>
        </div>
      )}

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-neutral-text-primary">生成记录</h2>
          <p className="text-xs text-neutral-text-secondary">
            完整兑换码仅显示一次，此处为脱敏前缀
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white">
          {listQuery.isLoading ? (
            <div className="px-4 py-12 text-center text-sm text-neutral-text-secondary">
              加载中...
            </div>
          ) : listQuery.error ? (
            <div className="px-4 py-6 text-sm text-red-600">
              加载失败：{listQuery.error.message || "未知错误"}
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-sm text-neutral-text-secondary">
                  <th className="px-4 py-3 font-medium">兑换码前缀</th>
                  <th className="px-4 py-3 text-right font-medium">金额</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">过期时间</th>
                  <th className="px-4 py-3 font-medium">创建时间</th>
                  <th className="px-4 py-3 font-medium">创建人</th>
                  <th className="px-4 py-3 font-medium">使用人</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-12 text-center text-sm text-neutral-text-secondary"
                    >
                      暂无生成记录
                    </td>
                  </tr>
                )}
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-slate-100 text-sm hover:bg-slate-50/50"
                  >
                    <td className="px-4 py-3 font-mono text-sm text-neutral-text-primary">
                      {item.codePrefix}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-sm">
                      {formatPrice(item.amount)}
                    </td>
                    <td className="px-4 py-3">{statusBadge(item.status)}</td>
                    <td className="px-4 py-3 text-neutral-text-secondary">
                      {formatDate(item.expiresAt)}
                    </td>
                    <td className="px-4 py-3 text-neutral-text-secondary">
                      {formatDate(item.createdAt)}
                    </td>
                    <td className="px-4 py-3 text-neutral-text-secondary">
                      {item.createdByEmail ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-neutral-text-secondary">
                      {item.usedByEmail ? (
                        <span>
                          {item.usedByEmail}
                          {item.usedAt && (
                            <span className="ml-2 text-xs text-neutral-text-secondary">
                              {formatDate(item.usedAt)}
                            </span>
                          )}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
