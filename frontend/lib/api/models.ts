import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

// --- Types ---

export interface ChannelInfo {
  id: number;
  providerName: string;
  multiplier: number;
  isDefault: boolean;
}

export interface ModelWithChannels {
  id: number;
  publicName: string;
  description: string | null;
  inputPrice: number;   // micro-yuan per 1K tokens
  outputPrice: number;  // micro-yuan per 1K tokens
  channels: ChannelInfo[];
}

export interface ModelDetail {
  id: number;
  publicName: string;
  providerName: string;
  providerModelId: string;
  description: string | null;
  inputPrice: number;
  outputPrice: number;
  status: string;
  channels: ChannelInfo[];
  createdAt: string;
}

// --- Hooks ---

export function useModels() {
  return useQuery<ModelWithChannels[], ApiClientError>({
    queryKey: ["models"],
    queryFn: () => apiClient<ModelWithChannels[]>("/models"),
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });
}

export function useModelDetail(id: number) {
  return useQuery<ModelDetail, ApiClientError>({
    queryKey: ["models", id],
    queryFn: () => apiClient<ModelDetail>(`/models/${id}`),
    enabled: id > 0,
  });
}
