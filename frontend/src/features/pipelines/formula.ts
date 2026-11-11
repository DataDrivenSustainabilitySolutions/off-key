/** Completing what is typed in a Formula or a Gate condition: the arriving features,
 * the functions the formula language knows and, in a condition, and, or and not. */

const FUNCTIONS: Record<string, string> = {
  abs: "abs(x)", sqrt: "sqrt(x)", log: "log(x)", log1p: "log1p(x)", exp: "exp(x)",
  min: "min(a, b, …)", max: "max(a, b, …)", clip: "clip(x, low, high)",
  if: "if(condition, when_true, when_false)",
};
const KEYWORDS: Record<string, string> = { and: "both hold", or: "either holds", not: "the opposite" };

export type Suggestion = { kind: "feature" | "function" | "keyword"; value: string; detail?: string };

/** The word being typed just before the caret: a bare name, or a name in an open backtick. */
export function typedWord(text: string, caret: number) {
  const before = text.slice(0, caret);
  if ((before.match(/`/g) ?? []).length % 2 === 1) {
    const start = before.lastIndexOf("`");
    const close = text.indexOf("`", caret);
    return { start, end: close < 0 ? caret : close + 1, prefix: before.slice(start + 1), quoted: true };
  }
  const match = /[A-Za-z_][A-Za-z0-9_]*$/.exec(before);
  // Letters right after a digit belong to a number, such as 1e5.
  if (!match || (match.index > 0 && /[0-9.]/.test(before[match.index - 1]!))) return undefined;
  const rest = /^[A-Za-z0-9_]*/.exec(text.slice(caret))![0];
  return { start: match.index, end: caret + rest.length, prefix: match[0], quoted: false };
}

/** What can complete a word: the arriving features first, then functions or, in a
 * condition, and, or and not. Names that start with the word come before ones that hold it. */
export function suggestions(
  word: { prefix: string; quoted: boolean },
  features: string[],
  labels: Record<string, string>,
  condition: boolean,
): Suggestion[] {
  const typed = word.prefix.toLocaleLowerCase();
  const all: Suggestion[] = [
    ...features.map((value) => ({ kind: "feature" as const, value, detail: labels[value] })),
    ...(word.quoted ? [] : Object.entries(FUNCTIONS)
      .map(([value, detail]) => ({ kind: "function" as const, value, detail }))),
    ...(word.quoted || !condition ? [] : Object.entries(KEYWORDS)
      .map(([value, detail]) => ({ kind: "keyword" as const, value, detail }))),
  ];
  const rank = (item: Suggestion) => {
    const value = item.value.toLocaleLowerCase();
    return value.startsWith(typed) ? 0 : value.includes(typed) ? 1 : 2;
  };
  const found = all.filter((item) => rank(item) < 2)
    .sort((left, right) => rank(left) - rank(right));
  // A word that is already complete needs no list.
  if (found.length === 1 && found[0]!.value === word.prefix) return [];
  return found.slice(0, 8);
}
