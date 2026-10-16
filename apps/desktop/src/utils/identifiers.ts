// UniProt's official 6/10-character grammar; suffix support matches the API.
// https://www.uniprot.org/help/accession_numbers
export function isUniprotAccession(value: string): boolean {
  return /^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-[0-9]{1,3})?$/.test(value.trim().toUpperCase());
}
