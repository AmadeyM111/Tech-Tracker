/** Display name and initials from a user ref (login when the name is empty). */

export interface PersonRef {
  id: string;
  login: string;
  first_name?: string | null;
  last_name?: string | null;
}

export function personName(person: PersonRef): string {
  const first = person.first_name?.trim() ?? "";
  const last = person.last_name?.trim() ?? "";
  if (last !== "" && first !== "") return `${last} ${first[0]}.`;
  if (last !== "") return last;
  if (first !== "") return first;
  return person.login;
}

export function personInitials(person: PersonRef): string {
  const first = person.first_name?.trim() ?? "";
  const last = person.last_name?.trim() ?? "";
  if (first !== "" && last !== "") return `${first[0]}${last[0]}`.toLocaleUpperCase("ru-RU");
  return personName(person).slice(0, 2).toLocaleUpperCase("ru-RU");
}
