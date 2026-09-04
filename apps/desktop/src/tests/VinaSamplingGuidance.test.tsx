import { render, screen } from "@testing-library/react";

import {
  VINA_SEARCH_VOLUME_WARNING_ANGSTROM3,
  VinaSamplingGuidance,
  vinaSearchVolume,
} from "../features/docking/VinaSamplingGuidance";

const smallBox = { center_x: 0, center_y: 0, center_z: 0, size_x: 20, size_y: 20, size_z: 20 };
const largeBox = { center_x: 0, center_y: 0, center_z: 0, size_x: 45, size_y: 60, size_z: 38 };

it("uses Vina's exact 27,000 A^3 warning boundary", () => {
  expect(vinaSearchVolume({ ...smallBox, size_x: 30, size_y: 30, size_z: 30 })).toBe(
    VINA_SEARCH_VOLUME_WARNING_ANGSTROM3,
  );
  const { rerender } = render(<VinaSamplingGuidance box={smallBox} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  rerender(<VinaSamplingGuidance box={largeBox} />);
  expect(screen.getByText("Vina large search-space warning")).toBeInTheDocument();
  expect(screen.getByText(/102,600 Å³.*3.8×.*27,000 Å³/)).toBeInTheDocument();
});

it("keeps exhaustiveness explicit and asks for a recorded sensitivity series", () => {
  render(<VinaSamplingGuidance box={largeBox} exhaustiveness={8} showWithinBoundary />);
  expect(screen.getByText(/selected exhaustiveness is 8; Ankora has not changed it/i)).toBeInTheDocument();
  expect(screen.getByText(/recorded sensitivity series/i)).toBeInTheDocument();
});
