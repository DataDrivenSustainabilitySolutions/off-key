import { expect, type Page } from "@playwright/test";

/** Inspect actual rendered SVG geometry, independent of the routing implementation. */
export async function pipelineRoutingSnapshot(page: Page) {
  return page.getByLabel("Pipeline graph", { exact: true }).evaluate((graph) => {
    const boxes = Array.from(graph.querySelectorAll<HTMLElement>(".react-flow__node")).map((element) => {
      const matrix = new DOMMatrix(getComputedStyle(element).transform);
      return { id: element.dataset.id!, x: matrix.e, y: matrix.f, width: element.offsetWidth, height: element.offsetHeight };
    });
    const violations: string[] = [];
    const blocked: string[] = [];
    const paths: Record<string, string> = {};
    for (const edge of graph.querySelectorAll<SVGGElement>(".react-flow__edge")) {
      const id = edge.getAttribute("data-testid")!.slice("rf__edge-".length);
      const path = edge.querySelector<SVGPathElement>(".react-flow__edge-path")!;
      paths[id] = path.getAttribute("d")!;
      if (edge.querySelector('[data-routing-status="blocked"]')) { blocked.push(id); continue; }
      const [sourceId, targetId] = JSON.parse(id) as [string, string];
      const source = boxes.find((box) => box.id === sourceId)!;
      const target = boxes.find((box) => box.id === targetId)!;
      const length = path.getTotalLength();
      const start = path.getPointAtLength(0);
      const end = path.getPointAtLength(length);
      // A wire leaves the middle of its output dot and ends at the rim of the input dot,
      // at most nine pixels before the card, so its arrowhead shows.
      const short = target.x - end.x;
      if (Math.abs(start.x - source.x - source.width) > 0.5 || Math.abs(start.y - source.y - source.height / 2) > 0.5
        || short < -0.5 || short > 9.5 || Math.abs(end.y - target.y - target.height / 2) > 0.5)
        violations.push(`${id}: detached endpoint`);
      if (/C|A/.test(paths[id]!)) violations.push(`${id}: non-orthogonal curve`);
      for (let distance = 0; distance <= length; distance += 2) {
        const point = path.getPointAtLength(distance);
        const collision = boxes.find((box) => point.x > box.x + 1 && point.x < box.x + box.width - 1
          && point.y > box.y + 1 && point.y < box.y + box.height - 1);
        if (collision) { violations.push(`${id}: crosses ${collision.id}`); break; }
      }
    }
    // Each dot, and each count of features, is drawn around the middle of its port.
    for (const port of graph.querySelectorAll<HTMLElement>(".react-flow__node .react-flow__handle")) {
      const drawn = getComputedStyle(port, "::after");
      const shift = new DOMMatrix(drawn.transform);
      const middle = {
        x: parseFloat(drawn.left) + parseFloat(drawn.width) / 2 + shift.e,
        y: parseFloat(drawn.top) + parseFloat(drawn.height) / 2 + shift.f,
      };
      if (Math.abs(middle.x - port.offsetWidth / 2) > 0.5 || Math.abs(middle.y - port.offsetHeight / 2) > 0.5)
        violations.push(`${port.closest<HTMLElement>(".react-flow__node")!.dataset.id}: ${port.dataset.handleid} dot off its port`);
    }
    return { violations, blocked, paths, boxes };
  });
}

export async function expectClearPipelineRouting(page: Page) {
  await expect.poll(async () => {
    const snapshot = await pipelineRoutingSnapshot(page);
    if (!Object.keys(snapshot.paths).length) return ["Connections not rendered"];
    return [...snapshot.violations, ...snapshot.blocked.map((id) => `Blocked: ${id}`)];
  }, { timeout: 3000, message: "Every rendered connection must stay attached and avoid box interiors" }).toEqual([]);
}
