import { isUniprotAccession } from "../utils/identifiers";

it.each(["P04637", "p04637-2", "A2BC19", "A0A023GPI8", "A0A023GPI8-123", " Q8WZ42 "])("accepts supported UniProt accession %s", (value) => {
  expect(isUniprotAccession(value)).toBe(true);
});
it.each(["123456", "P0463", "P046378", "P04637-9999", "A012345678", "A0A023GPI8/../../", ""])("rejects malformed accession %s", (value) => {
  expect(isUniprotAccession(value)).toBe(false);
});
