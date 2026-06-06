import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

// --- Types ---

export interface ProviderOption {
  id: number;
  name: string;
}

export interface AdminModelItem {
  id: number;
  publicName: string;
  providerId: number;
  providerName: string;
  providerModelId: string;
  description: string | null;
  inputPrice: number;   // micro-yuan per 1K tokens
  outputPrice: number;  // micro-yuan per 1K tokens
  multiplier: number;
  status: "active" | "inactive";
  createdAt: string;
}

export interface ModelCreateInput {
  publicName: string;
  providerId: number;
  providerModelId: string;
  description?: string;
  inputPrice: number;
  outputPrice: number;
  multiplier?: number;
}

export interface ModelUpdateInput {
  publicName?: string;
  providerId?: number;
  providerModelId?: string;
  description?: string;
  inputPrice?: number;
  outputPrice?: number;
  multiplier?: number;
}

// --- Hooks ---

export function useAdminModels() {
  return useQuery<AdminModelItem[], ApiClientError>({
    queryKey: ["admin", "models"],
    queryFn: () => apiClient<AdminModelItem[]>("/admin/models"),
  });
}

export function useCreateModel() {
  const queryClient = useQueryClient();

  return useMutation<AdminModelItem, ApiClientError, ModelCreateInput>({
    mutationFn: (data) =>
      apiClient<AdminModelItem>("/admin/models", {
        method: "POST",
        body: JSON.stringify({
          publicName: data.publicName,
          providerId: data.providerId,
          providerModelId: data.providerModelId,
          description: data.description ?? null,
          inputPrice: data.inputPrice,
          outputPrice: data.outputPrice,
          multiplier: data.multiplier ?? 1.0,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
      // Also invalidate the public models list so users see new models immediately
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useUpdateModel() {
  const queryClient = useQueryClient();

  return useMutation<AdminModelItem, ApiClientError, { id: number; data: ModelUpdateInput }>({
    mutationFn: ({ id, data }) =>
      apiClient<AdminModelItem>(`/admin/models/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useToggleModelStatus() {
  const queryClient = useQueryClient();

  return useMutation<AdminModelItem, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<AdminModelItem>(`/admin/models/${id}/status`, {
        method: "PATCH",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

// --- Provider hook (for dropdown) ---

export function useAdminProviders() {
  return useQuery<ProviderOption[], ApiClientError>({
    queryKey: ["admin", "providers"],
    queryFn: () => apiClient<ProviderOption[]>("/admin/providers/dropdown"),
    staleTime: 5 * 60 * 1000,
  });
}

// --- Delete ---

export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteModel() {
  const queryClient = useQueryClient();

  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/models/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
