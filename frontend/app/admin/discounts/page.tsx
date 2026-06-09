"use client";

import { useEffect, useMemo, useState } from "react";
import { Percent, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useTokenCoefficients,
  useUpdateGlobalCoefficient,
  useUpsertModelCoefficient,
  useDeleteModelCoefficient,
  type TokenCoefficientModelItem,
} from "@/lib/api/admin/token-coefficients";
import { useAdminModels, type AdminModelItem } from "@/lib/api/admin/models";
import { ApiClientError } from "@/lib/api/client";

function clampCoefficient(value: string): number | null {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0 || n > 1) return null;
  return n;
}

export default function DiscountsPage() {
  const overview = useTokenCoefficients();
  const models = useAdminModels();
  const updateGlobal = useUpdateGlobalCoefficient();
  const upsert = useUpsertModelCoefficient();
  const remove = useDeleteModelCoefficient();

  const [globalDraft, setGlobalDraft] = useState<string>("1");
  useEffect(() => {
    if (overview.data) setGlobalDraft(String(overview.data.globalCoefficient));
  }, [overview.data]);

  const overridesById = useMemo(() => {
    const map = new Map<number, TokenCoefficientModelItem>();
    (overview.data?.overrides ?? []).forEach((o) => map.set(o.modelId, o));
    return map;
  }, [overview.data]);

  const [editing, setEditing] = useState<{
    model: AdminModelItem;
    draft: string;
    error: string | null;
  } | null>(null);

  const handleSaveGlobal = async () => {
    const v = clampCoefficient(globalDraft);
    if (v === null) return;
    try {
      await updateGlobal.mutateAsync({ coefficient: v });
    } catch (e) {
      if (e instanceof ApiClientError) {
        alert(e.message);
      } else {
        throw e;
      }
    }
  };

  const handleSaveOverride = async () => {
    if (!editing) return;
    const v = clampCoefficient(editing.draft);
    if (v === null) {
      setEditing({ ...editing, error: "请输入 0–1 之间的小数" });
      return;
    }
    try {
      await upsert.mutateAsync({ modelId: editing.model.id, coefficient: v });
      setEditing(null);
    } catch (e) {
      if (e instanceof ApiClientError) {
        setEditing({ ...editing, error: e.message });
      } else {
        throw e;
      }
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-2">
        <Percent className="h-5 w-5" />
        <h1 className="text-xl font-semibold">折扣配置（Token 系数）</h1>
      </div>

      {/* Global */}
      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="text-sm font-medium text-slate-700">全局默认系数</h2>
        <p className="mt-1 text-xs text-slate-500">
          所有模型的默认折扣系数（0 &lt; x ≤ 1）。1.0 表示无折扣。
        </p>
        <div className="mt-4 flex items-end gap-3">
          <div className="w-40">
            <Label htmlFor="global-coefficient">系数</Label>
            <Input
              id="global-coefficient"
              type="number"
              step="0.01"
              min="0.01"
              max="1"
              value={globalDraft}
              onChange={(e) => setGlobalDraft(e.target.value)}
              disabled={overview.isLoading}
            />
          </div>
          <Button onClick={handleSaveGlobal} disabled={updateGlobal.isPending}>
            <Save className="mr-1 h-4 w-4" />
            保存
          </Button>
          {overview.data && (
            <span className="text-xs text-slate-500">
              最近更新：{new Date(overview.data.globalMeta.updatedAt).toLocaleString()}
              {overview.data.globalMeta.updatedByUsername
                ? ` by ${overview.data.globalMeta.updatedByUsername}`
                : ""}
            </span>
          )}
        </div>
      </section>

      {/* Per-model overrides */}
      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-6">
          <h2 className="text-sm font-medium text-slate-700">模型级覆盖</h2>
          <p className="mt-1 text-xs text-slate-500">
            为单个模型设置系数；未覆盖的模型使用全局值。
          </p>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>公开名称</TableHead>
              <TableHead>描述</TableHead>
              <TableHead>当前系数</TableHead>
              <TableHead>来源</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.data?.map((m) => {
              const ov = overridesById.get(m.id);
              return (
                <TableRow key={m.id}>
                  <TableCell className="font-medium">{m.publicName}</TableCell>
                  <TableCell className="text-slate-500">{m.description ?? "—"}</TableCell>
                  <TableCell>
                    {ov ? (
                      <Badge variant="success">{ov.coefficient.toFixed(2)}</Badge>
                    ) : (
                      <span className="text-slate-400">
                        {overview.data?.globalCoefficient.toFixed(2) ?? "—"} (全局)
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-slate-500">
                    {ov ? "覆盖" : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          setEditing({ model: m, draft: String(ov?.coefficient ?? overview.data?.globalCoefficient ?? 1), error: null })
                        }
                      >
                        {ov ? "修改" : "设置覆盖"}
                      </Button>
                      {ov && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => remove.mutate({ modelId: m.id })}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </section>

      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing && overridesById.has(editing.model.id) ? "修改" : "设置"}模型覆盖
            </DialogTitle>
            <DialogDescription>
              模型：{editing?.model.publicName}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="model-coefficient">系数 (0 &lt; x ≤ 1)</Label>
            <Input
              id="model-coefficient"
              type="number"
              step="0.01"
              min="0.01"
              max="1"
              value={editing?.draft ?? ""}
              onChange={(e) =>
                editing && setEditing({ ...editing, draft: e.target.value, error: null })
              }
            />
            {editing?.error && (
              <p className="text-xs text-red-600">{editing.error}</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              取消
            </Button>
            <Button onClick={handleSaveOverride} disabled={upsert.isPending}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
