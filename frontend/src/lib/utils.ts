import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** One or two letters from an address, such as "JD" for jane.doe@example.com. */
export const memberInitials = (email = "") => {
  const parts = email.split("@")[0]!.split(/[._+-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0]![0]! + parts[1]![0]! : parts[0]?.[0] ?? "?").toLocaleUpperCase();
};
