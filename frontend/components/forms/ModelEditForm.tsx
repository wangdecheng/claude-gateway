"use client";

import { useEffect, useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AdminModelItem, ModelCreateInput, ModelUpdateInput } from "@/lib/api/admin/models";

interface ProviderOption {
  id: number;
  name: string;
}

interface ModelEditFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: ModelCreateInput | ModelUpdateInput) => Promise<void>;
  model?: AdminModelItem | null; // null = create mode
  providers: ProviderOption[];
  isSubmitting: boolean;
  error?: string | null;
}

export function ModelEditForm({
  open,
  onOpenChange,
  onSubmit,
  model,
  providers,
  isSubmitting,
  error,
}: ModelEditFormProps) {
  const isEdit = !!model;
  const [selectedProvider, setSelectedProvider] = useState<string>("");

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm({
    defaultValues: {
      publicName: "",
      providerId: 0,
      providerModelId: "",
      description: "",
      inputPrice: 0,
      outputPrice: 0,
      multiplier: 1.0,
    },
  });

  useEffect(() => {
    if (open) {
      if (model) {
        reset({
          publicName: model.publicName,
          providerId: model.providerId,
          providerModelId: model.providerModelId,
          description: model.description || "",
          inputPrice: model.inputPrice,
          outputPrice: model.outputPrice,
          multiplier: model.multiplier,
        });
        setSelectedProvider(String(model.providerId));
      } else {
        reset({
          publicName: "",
          providerId: providers[0]?.id || 0,
          providerModelId: "",
          description: "",
          inputPrice: 0,
          outputPrice: 0,
          multiplier: 1.0,
        });
        setSelectedProvider(providers[0]?.id ? String(providers[0].id) : "");
      }
    }
  }, [open, model, reset, providers]);

  const onFormSubmit = handleSubmit(async (formData) => {
    const providerId = parseInt(selectedProvider, 10) || formData.providerId;
    const data: ModelCreateInput | ModelUpdateInput = {
      ...formData,
      providerId,
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
            {isEdit ? "修改模型信息或默认倍率" : "新增一个 AI 模型并设置默认渠道配置"}
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

          {/* Provider */}
          <div className="space-y-2">
            <Label htmlFor="providerId">
              上游供应商 <span className="text-red-500">*</span>
            </Label>
            <Select
              value={selectedProvider}
              onValueChange={(v) => {
                setSelectedProvider(v);
                setValue("providerId", parseInt(v, 10));
              }}
              disabled={isEdit}
            >
              <SelectTrigger id="providerId">
                <SelectValue placeholder="选择供应商" />
              </SelectTrigger>
              {isEdit && (
                <p className="text-xs text-muted-foreground mt-1">
                  供应商不可修改，如需更换请创建新模型
                </p>
              )}
              <SelectContent>
                {providers.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Internal Model ID */}
          <div className="space-y-2">
            <Label htmlFor="providerModelId">
              内部模型 ID <span className="text-red-500">*</span>
            </Label>
            <Input
              id="providerModelId"
              placeholder="如 claude-sonnet-4-7-20250501"
              maxLength={200}
              {...register("providerModelId", { required: "内部模型 ID 为必填项" })}
            />
            {errors.providerModelId && (
              <p className="text-sm text-red-500">{errors.providerModelId.message}</p>
            )}
          </div>

          {/* Multiplier */}
          <div className="space-y-2">
            <Label htmlFor="multiplier">默认倍率</Label>
            <Input
              id="multiplier"
              type="number"
              step="0.1"
              min="0.1"
              {...register("multiplier", {
                valueAsNumber: true,
                min: { value: 0.1, message: "倍率必须大于 0" },
              })}
            />
            {errors.multiplier && (
              <p className="text-sm text-red-500">{errors.multiplier.message}</p>
            )}
          </div>

          {/* Input Price */}
          <div className="space-y-2">
            <Label htmlFor="inputPrice">
              Input 单价 <span className="text-red-500">*</span>
            </Label>
            <p className="text-xs text-muted-foreground">
              单位: micro-yuan/1K tokens（如 150 = ¥0.015/1K tokens）
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
              单位: micro-yuan/1K tokens（如 600 = ¥0.06/1K tokens）
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
