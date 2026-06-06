import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

// --- Types ---

export interface KeyResponse {
  id: number;
  name: string;
  keyPrefix: string;
  status: string;
  createdAt: string;
  lastUsedAt: string | null;
}

export interface CreateKeyResponse extends KeyResponse {
  rawKey: string;
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
  return useMutation<CreateKeyResponse, ApiClientError, { name: string }>({
    mutationFn: (data) =>
      apiClient<CreateKeyResponse>("/keys", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keys"] });
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
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
