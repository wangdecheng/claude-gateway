import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

export interface UserChannel {
  id: number;
  channelName: string;
  multiplier: number;
  isDefault: boolean;
}

export interface ChannelModelRow {
  id: number;
  publicName: string;
  description: string | null;
  inputPrice: number;
  outputPrice: number;
  inputBasePrice: number;
  outputBasePrice: number;
}

export interface ChannelWithModels {
  channel: UserChannel;
  models: ChannelModelRow[];
}

export function useActiveChannels() {
  return useQuery<UserChannel[], ApiClientError>({
    queryKey: ["channels", "active"],
    queryFn: () => apiClient<UserChannel[]>("/providers/active"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useChannelModels(channelId: number) {
  return useQuery<ChannelWithModels, ApiClientError>({
    queryKey: ["channels", channelId, "models"],
    queryFn: () =>
      apiClient<ChannelWithModels>(`/providers/${channelId}/models`),
    enabled: channelId > 0,
    staleTime: 5 * 60 * 1000,
  });
}
