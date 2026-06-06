import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "./client";

// --- Types ---

export interface DailyStat {
  date: string;
  calls: number;
  tokens: number;
  costCents: number;
}

export interface UsageStats {
  todayCalls: number;
  todayTokens: number;
  todayCostCents: number;
  activeKeys: number;
  daily: DailyStat[];
}

export interface UsageRecord {
  id: number;
  model: string;
  requestTokens: number;
  responseTokens: number;
  totalTokens: number;
  costCents: number;
  createdAt: string;
}

export interface UsageHistory {
  records: UsageRecord[];
  total: number;
  page: number;
  pageSize: number;
}

// --- Hooks ---

export function useUsageStats(days: number = 30) {
  return useQuery<UsageStats, ApiClientError>({
    queryKey: ["usage", "stats", days],
    queryFn: () =>
      apiClient<UsageStats>(`/usage/stats?days=${days}`),
    refetchInterval: 60_000, // Auto-refresh every 60 seconds
  });
}

export function useUsageHistory(page: number = 1, pageSize: number = 20) {
  return useQuery<UsageHistory, ApiClientError>({
    queryKey: ["usage", "history", page, pageSize],
    queryFn: () =>
      apiClient<UsageHistory>(
        `/usage/history?page=${page}&pageSize=${pageSize}`
      ),
  });
}
