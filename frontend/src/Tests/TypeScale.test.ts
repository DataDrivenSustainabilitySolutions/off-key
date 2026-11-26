import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = path.resolve(import.meta.dirname, "..");
// The four weights of the type scale: regular, medium, emphasis and headline.
const WEIGHTS = new Set(["400", "500", "550", "600"]);
const CAPTION_PX = 12;

function sources(extension: string): Array<[string, string]> {
  return fs.readdirSync(SOURCE, { recursive: true, encoding: "utf8" })
    .filter(file => file.endsWith(extension) && !file.startsWith("Tests"))
    .map(file => [file, fs.readFileSync(path.join(SOURCE, file), "utf8")]);
}

function matches(files: Array<[string, string]>, pattern: RegExp, keep: (value: string) => boolean) {
  return files.flatMap(([file, text]) => [...text.matchAll(pattern)]
    .filter(match => keep(match[1] ?? ""))
    .map(match => `${file}: ${match[0]}`));
}

describe("type scale", () => {
  it("never sets text below the caption size", () => {
    expect(matches(sources(".css"), /font-size:\s*(\d+(?:\.\d+)?)px/g, size => Number(size) < CAPTION_PX)).toEqual([]);
    expect(matches(sources(".ts"), /fontSize:\s*(\d+(?:\.\d+)?)\b/g, size => Number(size) < CAPTION_PX)).toEqual([]);
  });

  it("uses only the scale's weights", () => {
    expect(matches(sources(".css"), /font-weight:\s*(\d+)/g, weight => !WEIGHTS.has(weight))).toEqual([]);
  });
});
