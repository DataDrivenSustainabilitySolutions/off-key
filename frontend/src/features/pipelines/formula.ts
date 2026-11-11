/** Completing what is typed in a Formula or a Gate condition: the arriving features,
 * the functions the formula language knows and, in a condition, and, or and not. */

const FUNCTIONS: Record<string, string> = {
  abs: "abs(x)", sqrt: "sqrt(x)", log: "log(x)", log1p: "log1p(x)", exp: "exp(x)",
  min: "min(a, b, …)", max: "max(a, b, …)", clip: "clip(x, low, high)",
  if: "if(condition, when_true, when_false)",
  mean: "mean(a, b, …)", sum: "sum(a, b, …)", hypot: "hypot(a, b, …)",
  sign: "sign(x): -1, 0 or 1", round: "round(x)", floor: "floor(x)", ceil: "ceil(x)",
  mod: "mod(x, divisor)", sin: "sin(radians)", cos: "cos(radians)", atan2: "atan2(y, x)",
  pi: "pi()",
};
/** Functions that take no value: accepting one writes its parentheses closed. */
export const CONSTANTS = new Set(["pi"]);
const KEYWORDS: Record<string, string> = { and: "both hold", or: "either holds", not: "the opposite" };

export type Suggestion = { kind: "feature" | "function" | "keyword"; value: string; detail?: string };

/** Whether and, or and not fit at the caret: in a condition, or in the condition of an
 * if(…), but not among the numbers another function takes. Plain parentheses only group. */
export function inCondition(text: string, caret: number, condition: boolean) {
  const calls: { name?: string; commas: number }[] = [];
  let quoted = false;
  for (let index = 0; index < caret; index++) {
    const character = text[index];
    if (character === "`") quoted = !quoted;
    if (quoted) continue;
    if (character === "(") {
      const name = /([A-Za-z_][A-Za-z0-9_]*)\s*$/.exec(text.slice(0, index))?.[1];
      calls.push({ name: name !== undefined && name in KEYWORDS ? undefined : name, commas: 0 });
    } else if (character === ")") calls.pop();
    else if (character === "," && calls.length) calls[calls.length - 1]!.commas += 1;
  }
  const call = calls.reverse().find((item) => item.name !== undefined);
  return call ? call.name === "if" && call.commas === 0 : condition;
}

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
 * condition, and, or and not. Features that start with the word come before ones that
 * hold it; a function or a keyword is offered only by its beginning. */
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
    return value.startsWith(typed) ? 0 : item.kind === "feature" && value.includes(typed) ? 1 : 2;
  };
  const found = all.filter((item) => rank(item) < 2)
    .sort((left, right) => rank(left) - rank(right));
  // A word that is already complete needs no list.
  if (found.length === 1 && found[0]!.value === word.prefix) return [];
  return found.slice(0, 8);
}
