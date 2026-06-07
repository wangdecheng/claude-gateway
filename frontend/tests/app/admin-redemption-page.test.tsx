import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminRedemptionPage from "@/app/admin/redemption/page";

const mockFetch = vi.fn();
global.fetch = mockFetch;
const mockWriteText = vi.fn();

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminRedemptionPage />
    </QueryClientProvider>
  );
}

describe("AdminRedemptionPage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockWriteText.mockReset();
    mockWriteText.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: mockWriteText,
      },
    });
  });

  it("renders the redemption form with five-day default", () => {
    renderWithProviders();

    expect(screen.getByRole("heading", { name: "兑换码管理" })).toBeInTheDocument();
    expect(screen.getByLabelText("有效天数")).toHaveValue(5);
  });

  it("shows the generated code after submit", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 1,
        code: "REDM-ABCD-EFGH-IJKL",
        codePrefix: "REDM-ABCD",
        amount: 500,
        status: "issued",
        expiresAt: "2026-06-12T00:00:00Z",
        createdAt: "2026-06-07T00:00:00Z",
      }),
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("金额"), "5");
    await user.click(screen.getByRole("button", { name: "生成兑换码" }));

    expect(await screen.findByText("REDM-ABCD-EFGH-IJKL")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/redemption",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
      })
    );
    expect(mockFetch.mock.calls[0][1]?.body).toBe(
      JSON.stringify({ amount: 500, expiresInDays: 5 })
    );
  });

  it("marks the generated code as copied", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 1,
        code: "REDM-ABCD-EFGH-IJKL",
        codePrefix: "REDM-ABCD",
        amount: 500,
        status: "issued",
        expiresAt: "2026-06-12T00:00:00Z",
        createdAt: "2026-06-07T00:00:00Z",
      }),
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("金额"), "5");
    await user.click(screen.getByRole("button", { name: "生成兑换码" }));
    await screen.findByText("REDM-ABCD-EFGH-IJKL");
    await user.click(screen.getByRole("button", { name: "复制兑换码" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    });
  });
});
