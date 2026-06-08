import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

export interface AdminChannelItem {
  id: number;
  modelId: number;
  modelName: string;
  modelStatus: "active" | "inactive";
  providerId: number;
  providerName: string;
  providerChannelName: string;
  providerMultiplier: number;
  providerStatus: "active" | "inactive";
  providerModel: string;
  isDefault: boolean;
  status: "active" | "inactive";
  createdAt: string;
}

export interface ChannelCreateInput {
  modelId: number;
  providerId: number;
  providerModel: string;
  isDefault?: boolean;
}

export interface ChannelUpdateInput {
  providerModel?: string;
  isDefault?: boolean;
}

export function useAdminChannels() {
  return useQuery<AdminChannelItem[], ApiClientError>({
    queryKey: ["admin", "channels"],
    queryFn: () => apiClient<AdminChannelItem[]>("/admin/channels"),
  });
}

export function useCreateChannel() {
  const queryClient = useQueryClient();

  return useMutation<AdminChannelItem, ApiClientError, ChannelCreateInput>({
    mutationFn: (data) =>
      apiClient<AdminChannelItem>("/admin/channels", {
        method: "POST",
        body: JSON.stringify({
          modelId: data.modelId,
          providerId: data.providerId,
          providerModel: data.providerModel,
          isDefault: data.isDefault ?? false,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useUpdateChannel() {
  const queryClient = useQueryClient();

  return useMutation<AdminChannelItem, ApiClientError, { id: number; data: ChannelUpdateInput }>({
    mutationFn: ({ id, data }) =>
      apiClient<AdminChannelItem>(`/admin/channels/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useToggleChannelStatus() {
  const queryClient = useQueryClient();

  return useMutation<AdminChannelItem, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<AdminChannelItem>(`/admin/channels/${id}/status`, {
        method: "PATCH",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

// --- Delete ---

export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteChannel() {
  const queryClient = useQueryClient();

  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/channels/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
