import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

// --- Types ---

export interface AdminProviderItem {
  id: number;
  name: string;
  channelName: string;
  multiplier: number;
  apiBaseUrl: string;
  authHeader: string;
  adapter: string;
  keyCount: number;
  activeKeyCount: number;
  status: "active" | "inactive";
  createdAt: string;
}

export interface ProviderKeyItem {
  id: number;
  keyPrefix: string;
  status: "active" | "revoked";
  createdAt: string;
}

export interface ProviderCreateInput {
  name: string;
  channelName: string;
  multiplier?: number;
  apiBaseUrl: string;
  authHeader?: string;
  adapter?: string;
  keys?: string[];
}

export interface ProviderUpdateInput {
  channelName?: string;
  multiplier?: number;
  apiBaseUrl?: string;
  authHeader?: string;
  adapter?: string;
}

export interface AddKeysResult {
  added: number;
  keyPrefixes: string[];
}

// --- Hooks ---

export function useAdminProviders() {
  return useQuery<AdminProviderItem[], ApiClientError>({
    queryKey: ["admin", "providers", "list"],
    queryFn: () => apiClient<AdminProviderItem[]>("/admin/providers"),
  });
}

export function useCreateProvider() {
  const queryClient = useQueryClient();

  return useMutation<AdminProviderItem, ApiClientError, ProviderCreateInput>({
    mutationFn: (data) =>
      apiClient<AdminProviderItem>("/admin/providers", {
        method: "POST",
        body: JSON.stringify({
          name: data.name,
          channelName: data.channelName,
          multiplier: data.multiplier ?? 1.0,
          apiBaseUrl: data.apiBaseUrl,
          authHeader: data.authHeader ?? "Authorization",
          adapter: data.adapter ?? "anthropic-messages",
          keys: data.keys ?? [],
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}

export function useUpdateProvider() {
  const queryClient = useQueryClient();

  return useMutation<AdminProviderItem, ApiClientError, { id: number; data: ProviderUpdateInput }>({
    mutationFn: ({ id, data }) =>
      apiClient<AdminProviderItem>(`/admin/providers/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}

export function useToggleProviderStatus() {
  const queryClient = useQueryClient();

  return useMutation<AdminProviderItem, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<AdminProviderItem>(`/admin/providers/${id}/status`, {
        method: "PATCH",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}

export function useProviderKeys(providerId: number) {
  return useQuery<ProviderKeyItem[], ApiClientError>({
    queryKey: ["admin", "providers", providerId, "keys"],
    queryFn: () => apiClient<ProviderKeyItem[]>(`/admin/providers/${providerId}/keys`),
    enabled: providerId > 0,
  });
}

export function useAddProviderKeys() {
  const queryClient = useQueryClient();

  return useMutation<AddKeysResult, ApiClientError, { providerId: number; keys: string[] }>({
    mutationFn: ({ providerId, keys }) =>
      apiClient<AddKeysResult>(`/admin/providers/${providerId}/keys`, {
        method: "POST",
        body: JSON.stringify({ keys }),
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers", variables.providerId, "keys"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}

export function useDisableProviderKey() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiClientError, { providerId: number; keyId: number }>({
    mutationFn: ({ providerId, keyId }) =>
      apiClient<void>(`/admin/providers/${providerId}/keys/${keyId}`, {
        method: "DELETE",
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers", variables.providerId, "keys"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}

export function useEnableProviderKey() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiClientError, { providerId: number; keyId: number }>({
    mutationFn: ({ providerId, keyId }) =>
      apiClient<void>(`/admin/providers/${providerId}/keys/${keyId}/enable`, {
        method: "PATCH",
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers", variables.providerId, "keys"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}

// --- Delete ---

export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteProvider() {
  const queryClient = useQueryClient();

  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/providers/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}
