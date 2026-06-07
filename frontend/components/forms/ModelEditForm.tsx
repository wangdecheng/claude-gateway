"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { AdminModelItem, ModelCreateInput, ModelUpdateInput } from "@/lib/api/admin/models";

interface ModelEditFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: ModelCreateInput | ModelUpdateInput) => Promise<void>;
  model?: AdminModelItem | null; // null = create mode
  isSubmitting: boolean;
  error?: string | null;
}

export function ModelEditForm({
  open,
  onOpenChange,
  onSubmit,
  model,
  isSubmitting,
  error,
}: ModelEditFormProps) {
  const isEdit = !!model;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm({
    defaultValues: {
      publicName: "",
      description: "",
      inputPrice: 0,
      outputPrice: 0,
    },
  });

  useEffect(() => {
    if (open) {
      if (model) {
        reset({
          publicName: model.publicName,
          description: model.description || "",
          inputPrice: model.inputPrice,
          outputPrice: model.outputPrice,
        });
      } else {
        reset({
          publicName: "",
          description: "",
          inputPrice: 0,
          outputPrice: 0,
        });
      }
    }
  }, [open, model, reset]);

  const onFormSubmit = handleSubmit(async (formData) => {
    const data: ModelCreateInput | ModelUpdateInput = {
      ...formData,
      description: formData.description || undefined,
    };
    await onSubmit(data);
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "编辑模型" : "添加模型"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "修改模型信息和定价" : "新增一个 AI 模型。供应商和上游模型映射请在渠道管理中配置。"}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onFormSubmit} className="space-y-4">
          {/* Public Name */}
          <div className="space-y-2">
            <Label htmlFor="publicName">
              公开名称 <span className="text-red-500">*</span>
            </Label>
            <Input
              id="publicName"
              placeholder="如 claude-sonnet-4-7"
              maxLength={100}
              {...register("publicName", { required: "公开名称为必填项" })}
            />
            {errors.publicName && (
              <p className="text-sm text-red-500">{errors.publicName.message}</p>
            )}
          </div>

          {/* Input Price */}
          <div className="space-y-2">
            <Label htmlFor="inputPrice">
              Input 单价 <span className="text-red-500">*</span>
            </Label>
            <p className="text-xs text-muted-foreground">
              存储单位: micro-yuan/1K tokens（展示时换算为 $/1M，例如 1500 = $1.50/1M）
            </p>
            <Input
              id="inputPrice"
              type="number"
              step="1"
              min="0"
              {...register("inputPrice", {
                valueAsNumber: true,
                required: "Input 单价为必填项",
                min: { value: 0, message: "单价不能为负数" },
              })}
            />
            {errors.inputPrice && (
              <p className="text-sm text-red-500">{errors.inputPrice.message}</p>
            )}
          </div>

          {/* Output Price */}
          <div className="space-y-2">
            <Label htmlFor="outputPrice">
              Output 单价 <span className="text-red-500">*</span>
            </Label>
            <p className="text-xs text-muted-foreground">
              存储单位: micro-yuan/1K tokens（展示时换算为 $/1M，例如 1500 = $1.50/1M）
            </p>
            <Input
              id="outputPrice"
              type="number"
              step="1"
              min="0"
              {...register("outputPrice", {
                valueAsNumber: true,
                required: "Output 单价为必填项",
                min: { value: 0, message: "单价不能为负数" },
              })}
            />
            {errors.outputPrice && (
              <p className="text-sm text-red-500">{errors.outputPrice.message}</p>
            )}
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="description">描述</Label>
            <Textarea
              id="description"
              rows={3}
              placeholder="可选的模型描述"
              {...register("description")}
            />
          </div>

          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "保存中..." : "保存"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
