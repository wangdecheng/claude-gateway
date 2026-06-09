import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

// --- Types ---

export interface TokenCoefficientModelItem {
  modelId: number;
  modelName: string;
  modelPublicName: string;
  coefficient: number;
  updatedAt: string;
  updatedByUsername: string | null;
}

export interface TokenCoefficientGlobalMeta {
  coefficient: number;
  updatedAt: string;
  updatedByUsername: string | null;
}

export interface TokenCoefficientsOverview {
  globalCoefficient: number;
  globalMeta: TokenCoefficientGlobalMeta;
  overrides: TokenCoefficientModelItem[];
}

// --- Hooks ---

export function useTokenCoefficients() {
  return useQuery<TokenCoefficientsOverview, ApiClientError>({
    queryKey: ["admin", "token-coefficients"],
    queryFn: () => apiClient<TokenCoefficientsOverview>("/admin/token-coefficients"),
  });
}

export function useUpdateGlobalCoefficient() {
  const qc = useQueryClient();
  return useMutation<TokenCoefficientGlobalMeta, ApiClientError, { coefficient: number }>({
    mutationFn: ({ coefficient }) =>
      apiClient<TokenCoefficientGlobalMeta>("/admin/token-coefficients/global", {
        method: "PUT",
        body: JSON.stringify({ coefficient }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "token-coefficients"] });
    },
  });
}

export function useUpsertModelCoefficient() {
  const qc = useQueryClient();
  return useMutation<
    TokenCoefficientModelItem,
    ApiClientError,
    { modelId: number; coefficient: number }
  >({
    mutationFn: ({ modelId, coefficient }) =>
      apiClient<TokenCoefficientModelItem>(
        `/admin/token-coefficients/models/${modelId}`,
        {
          method: "PUT",
          body: JSON.stringify({ coefficient }),
        }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "token-coefficients"] });
    },
  });
}

export function useDeleteModelCoefficient() {
  const qc = useQueryClient();
  return useMutation<void, ApiClientError, { modelId: number }>({
    mutationFn: ({ modelId }) =>
      apiClient<void>(`/admin/token-coefficients/models/${modelId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "token-coefficients"] });
    },
  });
}
