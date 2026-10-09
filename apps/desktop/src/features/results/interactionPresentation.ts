import type { InteractionContact } from "../../types/api";

export type InteractionDetail = "summary" | "all";

export function residueKey(contact: InteractionContact): string {
  const residue = contact.residue;
  return JSON.stringify([
    residue.chain_id, residue.sequence_number, residue.insertion_code, residue.residue_name,
  ]);
}

/** Family controls colour only; grouping must preserve the exact detector subtype. */
export function groupContacts(contacts: InteractionContact[]) {
  const grouped = new Map<string, InteractionContact[]>();
  for (const contact of contacts) {
    const key = JSON.stringify([residueKey(contact), contact.detector_type]);
    const group = grouped.get(key);
    if (group) group.push(contact);
    else grouped.set(key, [contact]);
  }
  return [...grouped.entries()].map(([key, items]) => ({ key, contacts: items }));
}

/** A view representative, never an energy ranking or a new scientific contact. */
export function representativeContact(
  contacts: InteractionContact[], selectedContactId: string | null,
): InteractionContact {
  return contacts.find((item) => item.contact_id === selectedContactId)
    ?? contacts.reduce((best, item) => (
      (item.distance_angstrom ?? Infinity) < (best.distance_angstrom ?? Infinity) ? item : best
    ));
}

export function displayedContacts(
  contacts: InteractionContact[], detail: InteractionDetail, selectedContactId: string | null,
): InteractionContact[] {
  return detail === "all" ? contacts : groupContacts(contacts).map(
    (group) => representativeContact(group.contacts, selectedContactId),
  );
}
