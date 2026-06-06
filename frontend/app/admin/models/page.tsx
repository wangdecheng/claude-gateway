"use client";

import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  flexRender,
} from "@tanstack/react-table";
import { Plus, Pencil, Power, PowerOff, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { ModelEditForm } from "@/components/forms/ModelEditForm";
import {
  useAdminModels,
  useAdminProviders,
  useCreateModel,
  useUpdateModel,
  useToggleModelStatus,
  useDeleteModel,
  type AdminModelItem,
  type ModelCreateInput,
  type ModelUpdateInput,
} from "@/lib/api/admin/models";
import { ApiClientError } from "@/lib/api/client";

// --- Column Helper ---

const columnHelper = createColumnHelper<AdminModelItem>();

function formatPrice(microYuan: number): string {
  const yuan = microYuan / 10_000; // micro-yuan / 1K tokens → ¥/1K tokens
  return `¥${yuan.toFixed(4)}`;
}

const COLUMNS = [
  columnHelper.accessor("publicName", {
    header: "公开名称",
    cell: (info) => <span className="font-medium">{info.getValue()}</span>,
  }),
  columnHelper.accessor("providerName", {
    header: "上游供应商",
  }),
  columnHelper.accessor("providerModelId", {
    header: "内部模型 ID",
    cell: (info) => (
      <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
        {info.getValue()}
      </code>
    ),
  }),
  columnHelper.accessor("multiplier", {
    header: "默认倍率",
    cell: (info) => <span>{info.getValue().toFixed(1)}x</span>,
  }),
  columnHelper.accessor("inputPrice", {
    header: "Input 单价",
    cell: (info) => (
      <span className="text-sm tabular-nums">{formatPrice(info.getValue())}</span>
    ),
  }),
  columnHelper.accessor("outputPrice", {
    header: "Output 单价",
    cell: (info) => (
      <span className="text-sm tabular-nums">{formatPrice(info.getValue())}</span>
    ),
  }),
  columnHelper.accessor("status", {
    header: "状态",
    cell: (info) => {
      const status = info.getValue();
      return (
        <Badge variant={status === "active" ? "success" : "muted"}>
          {status === "active" ? "上架" : "下架"}
        </Badge>
      );
    },
  }),
];

export default function AdminModelsPage() {
  const { data: models, isLoading, error } = useAdminModels();
  const { data: providers = [] } = useAdminProviders();
  const createMutation = useCreateModel();
  const updateMutation = useUpdateModel();
  const toggleMutation = useToggleModelStatus();
  const deleteMutation = useDeleteModel();

  // Form state
  const [formOpen, setFormOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<AdminModelItem | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Toggle confirmation state
  const [toggleTarget, setToggleTarget] = useState<AdminModelItem | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<AdminModelItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleCreate = () => {
    setEditingModel(null);
    setFormError(null);
    setFormOpen(true);
  };

  const handleEdit = (model: AdminModelItem) => {
    setEditingModel(model);
    setFormError(null);
    setFormOpen(true);
  };

  const handleFormSubmit = async (data: ModelCreateInput | ModelUpdateInput) => {
    setFormError(null);
    try {
      if (editingModel) {
        await updateMutation.mutateAsync({ id: editingModel.id, data });
      } else {
        await createMutation.mutateAsync(data as ModelCreateInput);
      }
      setFormOpen(false);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setFormError(err.message);
      } else {
        setFormError("操作失败，请重试");
      }
    }
  };

  const handleToggleConfirm = async () => {
    if (!toggleTarget) return;
    setToggleError(null);
    try {
      await toggleMutation.mutateAsync(toggleTarget.id);
      setToggleTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setToggleError(err.message);
      } else {
        setToggleError("操作失败，请重试");
      }
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("删除失败，请重试");
      }
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  const table = useReactTable({
    data: models || [],
    columns: COLUMNS,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div>
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-text-primary">模型管理</h1>
          <p className="text-sm text-neutral-text-secondary mt-1">
            添加、编辑、上下架 AI 模型
          </p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="h-4 w-4 mr-2" />
          添加模型
        </Button>
      </div>

      {/* Loading & Error States */}
      {isLoading && (
        <p className="text-sm text-neutral-text-secondary">加载中...</p>
      )}
      {error && (
        <p className="text-sm text-red-500">加载失败: {error.message}</p>
      )}

      {/* Table */}
      {!isLoading && !error && (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  ))}
                  <TableHead className="w-[120px]">操作</TableHead>
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={COLUMNS.length + 1}
                    className="text-center text-neutral-text-secondary"
                  >
                    暂无模型数据
                  </TableCell>
                </TableRow>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(row.original)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setToggleTarget(row.original)}
                        >
                          {row.original.status === "active" ? (
                            <PowerOff className="h-4 w-4 text-orange-500" />
                          ) : (
                            <Power className="h-4 w-4 text-green-500" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setDeleteTarget(row.original);
                            setDeleteError(null);
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create / Edit Form Dialog */}
      <ModelEditForm
        open={formOpen}
        onOpenChange={setFormOpen}
        onSubmit={handleFormSubmit}
        model={editingModel}
        providers={providers}
        isSubmitting={isSubmitting}
        error={formError}
      />

      {/* Toggle Status Confirmation Dialog */}
      <Dialog open={!!toggleTarget} onOpenChange={() => { setToggleTarget(null); setToggleError(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {toggleTarget?.status === "active" ? "下架模型" : "上架模型"}
            </DialogTitle>
            <DialogDescription>
              {toggleTarget?.status === "active" ? (
                <>
                  确定要下架 <strong>{toggleTarget?.publicName}</strong> 吗？
                  <br />
                  下架后，用户端模型列表将不再展示该模型，但已有的 sk 绑定不受影响。
                </>
              ) : (
                <>
                  确定要上架 <strong>{toggleTarget?.publicName}</strong> 吗？
                  <br />
                  上架后，用户端模型列表将即时可见。
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          {toggleError && (
            <p className="text-sm text-red-500">{toggleError}</p>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setToggleTarget(null)}>
              取消
            </Button>
            <Button
              onClick={handleToggleConfirm}
              disabled={toggleMutation.isPending}
              variant={toggleTarget?.status === "active" ? "destructive" : "primary"}
            >
              {toggleMutation.isPending
                ? "处理中..."
                : toggleTarget?.status === "active"
                  ? "确认下架"
                  : "确认上架"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => { setDeleteTarget(null); setDeleteError(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除模型</DialogTitle>
            <DialogDescription>
              确定要删除 <strong>{deleteTarget?.publicName}</strong> 吗？
              <br />
              删除后将无法通过该模型发起 API 请求。
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {deleteError}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
