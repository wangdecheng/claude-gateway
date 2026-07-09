import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

// --- Types ---

export interface KeyResponse {
  id: number;
  name: string;
  keyPrefix: string;
  status: string;
  channelId: number | null;
  channelName: string | null;
  createdAt: string;
  lastUsedAt: string | null;
  // 明文 sk；列表返回中始终存在，方便前端随时复制。
  rawKey: string;
}

export interface CreateKeyResponse extends KeyResponse {
  rawKey: string;
}

export interface CreateKeyInput {
  name: string;
  channelId: number;
}

// --- Hooks ---

export function useKeys() {
  return useQuery<KeyResponse[], ApiClientError>({
    queryKey: ["keys"],
    queryFn: () => apiClient<KeyResponse[]>("/keys"),
  });
}

export function useCreateKey() {
  const queryClient = useQueryClient();
  return useMutation<CreateKeyResponse, ApiClientError, CreateKeyInput>({
    mutationFn: (data) =>
      apiClient<CreateKeyResponse>("/keys", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keys"] });
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

export interface UpdateKeyInput {
  channelId: number | null; // null = 清除绑定（设为自动）
}

export function useUpdateKey() {
  const queryClient = useQueryClient();
  return useMutation<KeyResponse, ApiClientError, { id: number; data: UpdateKeyInput }>({
    mutationFn: ({ id, data }) =>
      apiClient<KeyResponse>(`/keys/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keys"] });
    },
  });
}

export function useRevokeKey() {
  const queryClient = useQueryClient();
  return useMutation<{ message: string }, ApiClientError, number>({
    mutationFn: (keyId) =>
      apiClient<{ message: string }>(`/keys/${keyId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keys"] });
    },
  });
}

// --- Base URL ---

export interface BaseUrlResponse {
  baseUrl: string;
}

export function useBaseUrl() {
  return useQuery<BaseUrlResponse, ApiClientError>({
    queryKey: ["baseUrl"],
    queryFn: () => apiClient<BaseUrlResponse>("/public-url"),
    staleTime: Infinity,
  });
}
