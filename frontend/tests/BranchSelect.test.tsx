import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BranchSelect } from "../src/components/BranchSelect";
import type { Branch } from "../src/infrastructure/api/branches";

const BRANCHES: Branch[] = [
  {
    code: "HU0001",
    name: "Biblioteca de Huelva",
    municipality: "Huelva",
    province: "Huelva",
    lat: 37.26,
    lng: -6.95,
  },
  {
    code: "SE0001",
    name: "Biblioteca de Sevilla",
    municipality: "Sevilla",
    province: "Sevilla",
    lat: 37.39,
    lng: -5.99,
  },
];

describe("BranchSelect", () => {
  it("calls onToggle with the branch code when a candidate is followed", async () => {
    const onToggle = vi.fn();
    render(<BranchSelect branches={BRANCHES} selected={[]} onToggle={onToggle} />);

    const [firstSeguir] = screen.getAllByRole("button", { name: "Seguir" });
    expect(firstSeguir).toBeDefined();
    await userEvent.click(firstSeguir as HTMLElement);

    expect(onToggle).toHaveBeenCalledWith(expect.stringMatching(/^(HU0001|SE0001)$/));
  });

  it("renders selected branches as removable chips that toggle off", async () => {
    const onToggle = vi.fn();
    render(<BranchSelect branches={BRANCHES} selected={["HU0001"]} onToggle={onToggle} />);

    // The selected branch shows as a chip; its candidate row is hidden.
    const chip = screen.getByRole("button", { name: /Dejar de seguir Biblioteca de Huelva/ });
    await userEvent.click(chip);
    expect(onToggle).toHaveBeenCalledWith("HU0001");
  });

  it("type-ahead filters candidates by name/municipality", async () => {
    render(<BranchSelect branches={BRANCHES} selected={[]} onToggle={() => {}} />);

    await userEvent.type(screen.getByLabelText("Buscar biblioteca"), "sevilla");
    expect(screen.getByText("Biblioteca de Sevilla")).toBeInTheDocument();
    expect(screen.queryByText("Biblioteca de Huelva")).not.toBeInTheDocument();
  });
});
