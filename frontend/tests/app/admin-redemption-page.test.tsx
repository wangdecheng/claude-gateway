import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminRedemptionPage from "@/app/admin/redemption/page";

const mockFetch = vi.fn();
global.fetch = mockFetch;

const mockCopyToClipboard = vi.fn<(text: string) => Promise<boolean>>();
vi.mock("@/lib/utils/clipboard", () => ({
  copyToClipboard: (text: string) => mockCopyToClipboard(text),
}));

interface MockListItem {
  id: number;
  codePrefix: string;
  amount: number;
  status: string;
  expiresAt: string;
  createdAt: string;
  createdByEmail: string | null;
  usedByEmail: string | null;
  usedAt: string | null;
}

interface MockHandlers {
  listItems?: MockListItem[];
}

function jsonResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}

/** Default mockFetch implementation: GET list returns [], POST returns the body the test set up. */
function setupFetch({ listItems = [] }: MockHandlers = {}) {
  mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/admin/redemption" && (!init?.method || init.method === "GET")) {
      return jsonResponse(listItems);
    }
    throw new Error(`Unexpected fetch in test: ${init?.method ?? "GET"} ${url}`);
  });
}

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
    mockCopyToClipboard.mockReset();
    mockCopyToClipboard.mockResolvedValue(true);
    setupFetch();
  });

  it("renders the redemption form with five-day default", async () => {
    renderWithProviders();

    expect(screen.getByRole("heading", { name: "兑换码管理" })).toBeInTheDocument();
    expect(screen.getByLabelText("有效天数")).toHaveValue(5);
    await waitFor(() => {
      expect(screen.getByText("暂无生成记录")).toBeInTheDocument();
    });
  });

  it("shows the generated code after submit", async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/admin/redemption" && init?.method === "POST") {
        return jsonResponse({
          id: 1,
          code: "REDM-ABCD-EFGH-IJKL",
          codePrefix: "REDM-ABCD",
          amount: 500,
          status: "issued",
          expiresAt: "2026-06-12T00:00:00Z",
          createdAt: "2026-06-07T00:00:00Z",
        });
      }
      if (url === "/api/admin/redemption") {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected fetch: ${init?.method ?? "GET"} ${url}`);
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("金额"), "5");
    await user.click(screen.getByRole("button", { name: "生成兑换码" }));

    expect(await screen.findByText("REDM-ABCD-EFGH-IJKL")).toBeInTheDocument();
    const postCall = mockFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(postCall?.[0]).toBe("/api/admin/redemption");
    expect(postCall?.[1]?.body).toBe(
      JSON.stringify({ amount: 500, expiresInDays: 5 })
    );
  });

  it("shows the success toast after copying", async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/admin/redemption" && init?.method === "POST") {
        return jsonResponse({
          id: 1,
          code: "REDM-ABCD-EFGH-IJKL",
          codePrefix: "REDM-ABCD",
          amount: 500,
          status: "issued",
          expiresAt: "2026-06-12T00:00:00Z",
          createdAt: "2026-06-07T00:00:00Z",
        });
      }
      if (url === "/api/admin/redemption") {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected fetch: ${init?.method ?? "GET"} ${url}`);
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("金额"), "5");
    await user.click(screen.getByRole("button", { name: "生成兑换码" }));
    await screen.findByText("REDM-ABCD-EFGH-IJKL");
    await user.click(screen.getByRole("button", { name: "复制兑换码" }));

    expect(await screen.findByText("兑换码已复制到剪贴板")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    });
    expect(mockCopyToClipboard).toHaveBeenCalledWith("REDM-ABCD-EFGH-IJKL");
  });

  it("shows an error toast when the clipboard copy fails", async () => {
    const user = userEvent.setup();
    mockCopyToClipboard.mockResolvedValue(false);
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/admin/redemption" && init?.method === "POST") {
        return jsonResponse({
          id: 1,
          code: "REDM-ABCD-EFGH-IJKL",
          codePrefix: "REDM-ABCD",
          amount: 500,
          status: "issued",
          expiresAt: "2026-06-12T00:00:00Z",
          createdAt: "2026-06-07T00:00:00Z",
        });
      }
      if (url === "/api/admin/redemption") {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected fetch: ${init?.method ?? "GET"} ${url}`);
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("金额"), "5");
    await user.click(screen.getByRole("button", { name: "生成兑换码" }));
    await screen.findByText("REDM-ABCD-EFGH-IJKL");
    await user.click(screen.getByRole("button", { name: "复制兑换码" }));

    expect(
      await screen.findByText("复制失败，请手动选择上方兑换码复制")
    ).toBeInTheDocument();
    // Stays as "复制兑换码", does NOT switch to "已复制".
    expect(screen.getByRole("button", { name: "复制兑换码" })).toBeInTheDocument();
  });

  it("renders the historical redemption codes", async () => {
    setupFetch({
      listItems: [
        {
          id: 2,
          codePrefix: "REDM-USED",
          amount: 1200,
          status: "used",
          expiresAt: "2026-06-12T00:00:00Z",
          createdAt: "2026-06-06T00:00:00Z",
          createdByEmail: "admin@example.com",
          usedByEmail: "alice@example.com",
          usedAt: "2026-06-07T00:00:00Z",
        },
        {
          id: 1,
          codePrefix: "REDM-NEW1",
          amount: 500,
          status: "issued",
          expiresAt: "2026-06-12T00:00:00Z",
          createdAt: "2026-06-05T00:00:00Z",
          createdByEmail: "admin@example.com",
          usedByEmail: null,
          usedAt: null,
        },
      ],
    });

    renderWithProviders();

    expect(await screen.findByText("REDM-USED")).toBeInTheDocument();
    expect(screen.getByText("REDM-NEW1")).toBeInTheDocument();
    expect(screen.getByText("未使用")).toBeInTheDocument();
    expect(screen.getByText("已使用")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("admin@example.com").length).toBeGreaterThan(0);
  });
});
