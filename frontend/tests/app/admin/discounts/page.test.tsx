import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/admin/token-coefficients", () => ({
  useTokenCoefficients: vi.fn(),
  useUpdateGlobalCoefficient: vi.fn(),
  useUpsertModelCoefficient: vi.fn(),
  useDeleteModelCoefficient: vi.fn(),
}));
vi.mock("@/lib/api/admin/models", () => ({
  useAdminModels: vi.fn(),
}));

import * as tc from "@/lib/api/admin/token-coefficients";
import * as models from "@/lib/api/admin/models";
import DiscountsPage from "@/app/admin/discounts/page";

function renderWithQuery(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("DiscountsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (models.useAdminModels as any).mockReturnValue({
      data: [
        { id: 1, publicName: "model-a", description: null, inputPrice: 0, outputPrice: 0, status: "active", createdAt: "" },
        { id: 2, publicName: "model-b", description: null, inputPrice: 0, outputPrice: 0, status: "active", createdAt: "" },
      ],
      isLoading: false,
    });
    (tc.useUpdateGlobalCoefficient as any).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    (tc.useUpsertModelCoefficient as any).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    (tc.useDeleteModelCoefficient as any).mockReturnValue({
      mutate: vi.fn(),
    });
  });

  it("renders the global coefficient value and a model list", async () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 0.8,
        globalMeta: { coefficient: 0.8, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [],
      },
      isLoading: false,
    });
    renderWithQuery(<DiscountsPage />);
    expect(screen.getByDisplayValue("0.8")).toBeInTheDocument();
    expect(screen.getByText("model-a")).toBeInTheDocument();
    expect(screen.getByText("model-b")).toBeInTheDocument();
    // Help text must mention the three in-scope fields and exclude cache_read.
    // The help paragraph splits field names into <code> children, so use a
    // function matcher that joins the element's full text content. Radix
    // Dialog renders the (closed) dialog in the DOM, so use getAllByText.
    const helpText = (content: string, element: Element | null) => {
      if (!element) return false;
      const fullText = (element.textContent ?? "").replace(/\s+/g, " ");
      return (
        fullText.includes("cache_read_input_tokens") &&
        fullText.includes("不参与折扣") &&
        fullText.includes("input_tokens") &&
        fullText.includes("cache_creation_input_tokens") &&
        fullText.includes("output_tokens")
      );
    };
    expect(screen.getAllByText(helpText).length).toBeGreaterThanOrEqual(1);
  });

  it("shows an existing override badge", () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 0.5,
        globalMeta: { coefficient: 0.5, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [
          { modelId: 1, modelName: "m1", modelPublicName: "model-a", coefficient: 0.3, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        ],
      },
      isLoading: false,
    });
    renderWithQuery(<DiscountsPage />);
    expect(screen.getByText("0.30")).toBeInTheDocument(); // Badge shows 0.30
    expect(screen.getByText("修改")).toBeInTheDocument(); // existing override
  });

  it("calls useUpdateGlobalCoefficient on save", async () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 1.0,
        globalMeta: { coefficient: 1.0, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [],
      },
      isLoading: false,
    });
    const mutate = vi.fn().mockResolvedValue({});
    (tc.useUpdateGlobalCoefficient as any).mockReturnValue({
      mutateAsync: mutate,
      isPending: false,
    });
    renderWithQuery(<DiscountsPage />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("系数");
    await user.clear(input);
    await user.type(input, "0.5");
    await user.click(screen.getByRole("button", { name: /保存/ }));
    await waitFor(() => {
      expect(mutate).toHaveBeenCalledWith({ coefficient: 0.5 });
    });
  });

  it("shows the same field-scope hint in the per-model dialog", async () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 1.0,
        globalMeta: { coefficient: 1.0, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [],
      },
      isLoading: false,
    });
    renderWithQuery(<DiscountsPage />);
    const user = userEvent.setup();
    // Open the per-model override dialog (button label is "设置覆盖" when none)
    await user.click(screen.getAllByRole("button", { name: /设置覆盖/ })[0]);
    // The dialog carries the same help text (split across <code> children).
    // Radix Dialog always renders the content in the DOM, so two matches are
    // expected: one for the global help paragraph, one for the dialog body.
    const dialogHelpText = (content: string, element: Element | null) => {
      if (!element) return false;
      const fullText = (element.textContent ?? "").replace(/\s+/g, " ");
      return (
        fullText.includes("cache_read_input_tokens") &&
        fullText.includes("不参与折扣") &&
        fullText.includes("input_tokens") &&
        fullText.includes("cache_creation_input_tokens") &&
        fullText.includes("output_tokens")
      );
    };
    const matches = await screen.findAllByText(dialogHelpText);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});
