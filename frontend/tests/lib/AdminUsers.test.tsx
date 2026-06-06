import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAdminUsers, useToggleUserStatus } from "@/lib/api/admin/users";

const mockFetch = vi.fn();
global.fetch = mockFetch;

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("admin users API hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads users from the admin users endpoint", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 2,
          email: "user@example.com",
          balance: 1234,
          role: "user",
          status: "active",
          createdAt: "2026-06-06T00:00:00Z",
        },
      ],
    });

    const { result } = renderHook(() => useAdminUsers(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/users",
      expect.objectContaining({ credentials: "include" })
    );
    expect(result.current.data?.[0].email).toBe("user@example.com");
  });

  it("toggles user status through the admin users status endpoint", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 2,
        email: "user@example.com",
        balance: 1234,
        role: "user",
        status: "disabled",
        createdAt: "2026-06-06T00:00:00Z",
      }),
    });

    const { result } = renderHook(() => useToggleUserStatus(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(2);
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/users/2/status",
      expect.objectContaining({
        credentials: "include",
        method: "PATCH",
      })
    );
  });
});
