import { fireEvent, render, screen } from "@testing-library/react";

import {
  applyVinaSamplingProtocol,
  vinaSamplingProtocolLabel,
  VinaSamplingProtocolControl,
} from "../features/docking/VinaSamplingProtocol";

const custom = {
  sampling_protocol: "custom" as const,
  cpu_threads: 4,
  seed: 42,
  exhaustiveness: 16,
  num_modes: 12,
  min_rmsd_angstrom: 2,
  energy_range_kcal_mol: 7,
  timeout_minutes: 60,
};

it("applies the exact purpose-labelled Vina starting protocols", () => {
  expect(applyVinaSamplingProtocol(custom, "screening")).toMatchObject({
    sampling_protocol: "screening",
    exhaustiveness: 8,
    num_modes: 9,
    min_rmsd_angstrom: 1,
    energy_range_kcal_mol: 3,
  });
  expect(applyVinaSamplingProtocol(custom, "pose_refinement")).toMatchObject({
    sampling_protocol: "pose_refinement",
    exhaustiveness: 32,
    num_modes: 20,
    min_rmsd_angstrom: 1,
    energy_range_kcal_mol: 5,
  });
  expect(applyVinaSamplingProtocol(custom, "custom")).toEqual(custom);
  expect(vinaSamplingProtocolLabel(undefined)).toBe("Unlabelled historical");
});

it("labels presets as starting protocols rather than convergence evidence", () => {
  const onChange = vi.fn();
  render(
    <VinaSamplingProtocolControl
      protocol="screening"
      disabled={false}
      onChange={onChange}
    />,
  );

  expect(screen.getByText(/not evidence of convergence or publication suitability/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pose refinement" }));
  expect(onChange).toHaveBeenCalledWith("pose_refinement");
});
