import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";

describe("Dialog", () => {
  it("renders content on an opaque project surface", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>编辑渠道</DialogTitle>
          <DialogDescription>配置上游模型 ID。</DialogDescription>
        </DialogContent>
      </Dialog>
    );

    expect(screen.getByRole("dialog")).toHaveClass("bg-neutral-surface");
    expect(screen.getByRole("dialog")).not.toHaveClass("bg-background");
  });
});
