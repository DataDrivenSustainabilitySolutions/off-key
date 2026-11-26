import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = path.resolve(import.meta.dirname, "..");
const CORNER = /^(var\(--radius(-control|-round)?\)|0|inherit|50%)$/u;

function sources(extension: string): Array<[string, string]> {
  return fs.readdirSync(SOURCE, { recursive: true, encoding: "utf8" })
    .filter(file => file.endsWith(extension) && !file.startsWith("Tests"))
    .map(file => [file, fs.readFileSync(path.join(SOURCE, file), "utf8")]);
}

describe("corners", () => {
  it("use the app's radius tokens, zero or a circle", () => {
    const stray = sources(".css").flatMap(([file, text]) => [...text.matchAll(/border-radius:\s*([^;}!]+)/gu)]
      .filter(match => !(match[1] ?? "").trim().split(/\s+/u).every(part => CORNER.test(part)))
      .map(match => `${file}: ${match[0].trim()}`));
    expect(stray).toEqual([]);
  });
});
