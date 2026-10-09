import { displayedContacts, groupContacts, residueKey } from "../features/results/interactionPresentation";
import { contact } from "./fixtures/interactionPresentation";

it.each([
  ["HBDonor", "HBAcceptor"], ["FaceToFace", "EdgeToFace"], ["CationPi", "PiCation"],
  ["Anionic", "Cationic"], ["XBDonor", "XBAcceptor"], ["MetalDonor", "MetalAcceptor"],
])("does not merge %s and %s even though they share a colour", (first, second) => {
  expect(groupContacts([contact(0, first), contact(1, second)])).toHaveLength(2);
});

it("distinguishes chains, insertions, sequence numbers and residue names", () => {
  const base = contact(0);
  const contacts = [base, ...[
    { chain_id: "B" }, { insertion_code: "A" }, { sequence_number: 124 }, { residue_name: "HIS" },
  ].map((fields, index) => ({ ...contact(index + 1), residue: { ...base.residue, ...fields } }))];
  expect(new Set(contacts.map(residueKey)).size).toBe(5);
  expect(groupContacts(contacts)).toHaveLength(5);
});

it("retains all 30 contacts without mutating the input when showing one representative", () => {
  const contacts = Array.from({ length: 30 }, (_, index) => contact(index));
  const original = JSON.stringify(contacts);
  expect(groupContacts(contacts)[0].contacts).toHaveLength(30);
  expect(displayedContacts(contacts, "summary", null)).toEqual([contacts[0]]);
  expect(displayedContacts(contacts, "all", null)).toBe(contacts);
  expect(JSON.stringify(contacts)).toBe(original);
});

it("shows the exact selected contact in summary mode instead of silently changing the selection", () => {
  const contacts = Array.from({ length: 30 }, (_, index) => contact(index));
  expect(displayedContacts(contacts, "summary", "contact-29")).toEqual([contacts[29]]);
});

it("uses recorded distance rather than list order and handles null distances and empty records", () => {
  const missing = { ...contact(0), distance_angstrom: null };
  expect(displayedContacts([missing, contact(2), contact(1)], "summary", null)).toEqual([contact(1)]);
  expect(displayedContacts([missing], "summary", null)).toEqual([missing]);
  expect(displayedContacts([], "summary", null)).toEqual([]);
});
