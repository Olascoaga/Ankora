import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ankoraApi } from "../api/client";
import { PoseInteractionPanel } from "../features/results/PoseInteractionPanel";
import type { InteractionContact } from "../types/api";
import type { ViewerContact, ViewerSelection } from "../viewer/adapter";
import { analysis, contact, entry, inventory, molecule } from "./fixtures/interactionPresentation";

// Spy only at the viewer boundary; exercise the actual panel, diagram, table
// and API client. No synthetic fixture is presented as a detector result.
vi.mock("../viewer/MolecularViewer", () => ({
  MolecularViewer: ({ interactionContacts, selectedContactId, selection }: {
    interactionContacts: ViewerContact[]; selectedContactId: string | null; selection: ViewerSelection | null;
  }) => <div data-testid="viewer-contact-evidence"
    data-contacts={JSON.stringify(interactionContacts)}
    data-selected={selectedContactId ?? ""}
    data-selection={JSON.stringify(selection)} />,
}));

async function open(contacts: InteractionContact[], extraRecord = false) {
  const record = analysis(contacts);
  const records = [record, ...(extraRecord ? [{ ...analysis([contact(0, "HBDonor")]), analysis_id: "other-analysis" }] : [])];
  const listPoses = vi.spyOn(ankoraApi, "listResultPoses").mockResolvedValue(inventory);
  vi.spyOn(ankoraApi, "listPoseInteractionAnalyses").mockResolvedValue(records);
  const create = vi.spyOn(ankoraApi, "analyzePoseInteractions");
  const original = JSON.stringify(records);
  render(<PoseInteractionPanel entry={entry} molecule={molecule} onClose={() => {}} />);
  await screen.findByRole("region", { name: "Interaction display" });
  return { record, records, original, create, listPoses };
}

function drawn(): ViewerContact[] {
  return JSON.parse(screen.getByTestId("viewer-contact-evidence").getAttribute("data-contacts")!);
}

it("keeps 30 atomic contacts in the table and ×30 in 2D while summarizing 3D, then expands both pictures", async () => {
  const data = await open(Array.from({ length: 30 }, (_, index) => contact(index)));
  const diagram = screen.getByRole("img", { name: "2D pose interaction diagram" });
  const table = screen.getByRole("region", { name: "Pose interaction evidence" });
  expect(screen.getByText("30 / 30 atom contacts")).toBeInTheDocument();
  expect(screen.getByText("Hydrophobic ×30")).toBeInTheDocument();
  expect(within(table).getAllByRole("row")).toHaveLength(31);
  expect(diagram.querySelectorAll(".interaction-contact line")).toHaveLength(1);
  expect(drawn()).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "All atom contacts" }));
  expect(diagram.querySelectorAll(".interaction-contact line")).toHaveLength(30);
  expect(drawn()).toHaveLength(30);
  expect(within(table).getAllByRole("row")).toHaveLength(31);
  expect(JSON.stringify(data.records)).toBe(data.original);
  expect(data.create).not.toHaveBeenCalled();
});

it("filters exact subtypes consistently across the table, 2D and 3D and clears stale selection", async () => {
  await open([contact(0), contact(1, "HBDonor"), contact(2, "HBAcceptor")]);
  const table = screen.getByRole("region", { name: "Pose interaction evidence" });
  fireEvent.click(within(table).getByRole("button", { name: "Hydrophobic" }));
  expect(screen.getByTestId("viewer-contact-evidence")).toHaveAttribute("data-selected", "contact-0");
  fireEvent.change(screen.getByRole("combobox", { name: "Interaction type" }), { target: { value: "HBAcceptor" } });
  expect(screen.getByText("1 / 3 atom contacts")).toBeInTheDocument();
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(drawn().map((item) => item.contactId)).toEqual(["contact-2"]);
  expect(screen.getByTestId("viewer-contact-evidence")).toHaveAttribute("data-selected", "");
  expect(screen.getByTestId("viewer-contact-evidence")).toHaveAttribute("data-selection", "null");
  const diagram = screen.getByRole("img", { name: "2D pose interaction diagram" });
  expect(within(diagram).queryByText("H-donor")).not.toBeInTheDocument();
  expect(within(diagram).getByText("H-acceptor")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Interaction type" }), { target: { value: "" } });
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  expect(drawn()).toHaveLength(3);
});

it("replaces a summary representative with the selected table contact in both pictures", async () => {
  await open([contact(0), contact(1)]);
  const table = screen.getByRole("region", { name: "Pose interaction evidence" });
  fireEvent.click(within(table).getAllByRole("button", { name: "Hydrophobic" })[1]);
  expect(drawn().map((item) => item.contactId)).toEqual(["contact-1"]);
  const diagram = screen.getByRole("img", { name: "2D pose interaction diagram" });
  expect(within(diagram).getByRole("button", { name: /^contact-1:/ })).toBeInTheDocument();
  expect(screen.getByTestId("viewer-contact-evidence")).toHaveAttribute("data-selected", "contact-1");
});

it("does not confuse summary contacts with missing geometry or hide positioned siblings", async () => {
  await open([{ ...contact(0), ligand_point: null, protein_point: null }, contact(1)]);
  expect(drawn().map((item) => item.contactId)).toEqual(["contact-1"]);
  expect(screen.getByText(/1 of 2 filtered contacts were/)).toBeInTheDocument();
  expect(screen.getByText("Hydrophobic ×2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "All atom contacts" }));
  expect(drawn()).toHaveLength(1);
  expect(screen.getByText(/1 of 2 filtered contacts were/)).toBeInTheDocument();
});

it("resets detail and type filters when opening a different immutable analysis", async () => {
  await open([contact(0), contact(1, "HBAcceptor")], true);
  fireEvent.change(screen.getByRole("combobox", { name: "Interaction type" }), { target: { value: "Hydrophobic" } });
  fireEvent.click(screen.getByRole("button", { name: "All atom contacts" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Recorded analysis" }), { target: { value: "other-analysis" } });
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Interaction type" })).toHaveValue(""));
  expect(screen.getByRole("button", { name: "Residue summary" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("1 / 1 atom contacts")).toBeInTheDocument();
  expect(drawn().map((item) => item.contactId)).toEqual(["contact-0"]);
});

it("shows an empty record without generating contacts or requiring a new analysis", async () => {
  const data = await open([]);
  expect(screen.getByText("0 / 0 atom contacts")).toBeInTheDocument();
  expect(screen.getByText("No supported contacts met this recorded profile.")).toBeInTheDocument();
  expect(drawn()).toEqual([]);
  expect(data.create).not.toHaveBeenCalled();
});
