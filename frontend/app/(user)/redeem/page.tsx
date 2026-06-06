"use client";

import { RedemptionInput } from "@/components/forms/RedemptionInput";
import { useRedemptionHistory } from "@/lib/api/redemption";
import { maskCode } from "@/lib/utils/mask";
import { formatPrice } from "@/lib/utils/format";

export default function RedeemPage() {
  const { data, isLoading } = useRedemptionHistory();

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold mb-6">兑换码</h1>
        <RedemptionInput />
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4">兑换记录</h2>

        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-12 bg-neutral-bg rounded-md animate-pulse"
              />
            ))}
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="text-center py-12 text-neutral-text-muted">
            <p>还没有兑换记录。输入兑换码激活余额。</p>
          </div>
        ) : (
          <div className="border border-neutral-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-border bg-neutral-bg">
                  <th className="text-left px-4 py-3 font-medium text-neutral-text-secondary">
                    时间
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-neutral-text-secondary">
                    兑换码
                  </th>
                  <th className="text-right px-4 py-3 font-medium text-neutral-text-secondary">
                    金额
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-neutral-border last:border-0"
                  >
                    <td className="px-4 py-3 font-mono text-sm text-neutral-text-secondary">
                      {new Date(item.createdAt).toLocaleDateString("zh-CN")}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm">
                      {maskCode(item.codeMasked)}
                    </td>
                    <td className="px-4 py-3 font-mono text-sm text-right">
                      {formatPrice(item.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
