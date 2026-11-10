// @vitest-environment node
import { describe, expect, it } from "vitest";
import { placeBeside, type Box } from "@/features/pipelines/anchoredPanel";

const box = (left: number, top: number, width = 224, height = 144): Box =>
  ({ left, top, right: left + width, bottom: top + height });
const area = box(12, 180, 1400, 700);
const panel = { width: 340, height: 700 };

describe("settings beside their card", () => {
  it("open below a card in a row, so its neighbours stay in view", () => {
    const card = box(300, 400);
    const spot = placeBeside(card, panel, area, [box(590, 400), box(880, 400)]);
    expect(spot).toEqual({ left: 300, top: 556, maxHeight: 880 - 556 });
  });

  it("open at full height beside a card with nothing next to it", () => {
    const spot = placeBeside(box(300, 400), panel, area, []);
    expect(spot).toEqual({ left: 536, top: 180, maxHeight: 700 });
  });

  it("go above when below would cover the zoom controls", () => {
    const card = box(300, 500);
    const spot = placeBeside(card, panel, area, [box(590, 500)], [box(20, 820, 240, 44)]);
    expect(spot).toEqual({ left: 300, top: 180, maxHeight: 500 - 12 - 180 });
  });

  it("never cover their own card, even when every side covers another", () => {
    const card = box(1100, 640);
    const crowded = [box(600, 640), box(800, 300), box(1100, 300)];
    const spot = placeBeside(card, panel, area, crowded);
    const placed = { left: spot.left, top: spot.top, right: spot.left + 340, bottom: spot.top + spot.maxHeight };
    expect(placed.right <= card.left || placed.left >= card.right || placed.bottom <= card.top || placed.top >= card.bottom).toBe(true);
  });

  it("leave their own card clear near the edge, even if that covers more of the others", () => {
    const card = box(300, 650);
    const spot = placeBeside(card, panel, area, [box(400, 250), box(550, 550)]);
    const placed = { left: spot.left, top: spot.top, right: spot.left + 340, bottom: spot.top + spot.maxHeight };
    expect(placed.right <= card.left || placed.left >= card.right || placed.bottom <= card.top || placed.top >= card.bottom).toBe(true);
  });

  it("leave the zoom controls usable, even if that covers more of the others", () => {
    const card = box(20, 450);
    const controls = box(20, 820, 240, 44);
    const spot = placeBeside(card, panel, area, [box(20, 200), box(300, 450)], [controls]);
    const placed = { left: spot.left, top: spot.top, right: spot.left + 340, bottom: spot.top + spot.maxHeight };
    expect(placed.right <= controls.left || placed.left >= controls.right
      || placed.bottom <= controls.top || placed.top >= controls.bottom).toBe(true);
  });
});
