import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import {
  addTestCharger,
  fixtureEntityId,
  removeTestCharger,
} from "./helpers/collection";
import { ingressOptions } from "./helpers/mqtt";
import { loginWithEmail } from "./helpers/auth";
import { publishPipelineSamples as publishSamples } from "./helpers/pipelineSamples";
import type { OperationalStatus } from "../src/types/monitoring";
import type {
  PipelineActivationView,
  PipelineCatalog,
  PipelineView,
  PipelineWorkspace,
  PipelineValidationReport,
} from "../src/types/pipelines.generated";
import type { PipelineState } from "../src/features/pipelines/diagnostics";

const selected = (page: Page) =>
  page.getByRole("combobox", { name: "Selected component", exact: true });
const connect = (page: Page, source: string) =>
  page
    .getByRole("combobox", { name: "Connect input from", exact: true })
    .selectOption(source);
const add = async (page: Page, name: string) => {
  await page.getByRole("button", { name: `Add ${name}`, exact: true }).click();
};
const processingId = (number: number) =>
  `processing_${String(number).padStart(2, "0")}_${"p".repeat(50)}`;

async function buildBranchedGraph(
  page: Page,
  adaptive: boolean,
  slots: Record<string, string>,
) {
  const canvas = page.getByLabel("Pipeline graph", { exact: true });
  const bounds = (await canvas.boundingBox())!;
  await page
    .getByRole("button", { name: "Add Select features", exact: true })
    .dragTo(canvas, { targetPosition: { x: 160, y: 120 } });
  const dropped = page.locator(
    '.react-flow__node[data-id="features_select_1"]',
  );
  await expect(dropped).toBeVisible();
  const position = (await dropped.boundingBox())!;
  expect(Math.abs(position.x - bounds.x - 160)).toBeLessThan(3);
  expect(Math.abs(position.y - bounds.y - 120)).toBeLessThan(3);
  await connect(page, "input");
  await page
    .getByRole("checkbox", { name: `voltage · ${slots.voltage!}`, exact: true })
    .check();
  await page
    .getByRole("checkbox", { name: `current · ${slots.current!}`, exact: true })
    .check();
  await add(page, adaptive ? "Online standard scaling" : "Standard scaling");
  await connect(page, "features_select_1");
  await add(page, adaptive ? "Online uncentered PCA" : "Centered PCA");
  await connect(page, `${adaptive ? "adaptive" : "static"}_standard_scaler_1`);
  if (adaptive)
    await page.getByRole("spinbutton", { name: "N0", exact: true }).fill("4");
  await add(page, "Select features");
  await connect(page, "input");
  await page
    .getByRole("checkbox", {
      name: `temperature · ${slots.temperature!}`,
      exact: true,
    })
    .check();
  await add(page, "Merge features");
  await connect(page, adaptive ? "adaptive_uncentered_pca_1" : "static_pca_1");
  await connect(page, "features_select_2");
  await selected(page).selectOption("detector");
  await page
    .getByRole("button", {
      name: "Disconnect input from detector",
      exact: true,
    })
    .click();
  await connect(page, "features_merge_1");
  await page
    .getByText("Input slots and learning settings", { exact: true })
    .click();
  await page
    .getByRole("spinbutton", {
      name: adaptive
        ? "Detector learning updates before calibration"
        : "Training observations",
      exact: true,
    })
    .fill(adaptive ? "20" : "40");
  await page
    .getByRole("spinbutton", { name: "Calibration observations", exact: true })
    .fill("8");
  await page.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Valid processing graph", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Arrange", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Arrange", exact: true }),
  ).toBeEnabled();
}

test.describe("visual pipeline real infrastructure", () => {
  test.setTimeout(600_000);
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("token_storage_type");
      sessionStorage.removeItem("auth_token");
    });
    await page.context().clearCookies();
    await page.goto("/login");
    await loginWithEmail(
      page,
      process.env.SUPERUSER_MAIL ?? "admin@example.com",
      { rememberMe: true },
    );
    const token = await page.evaluate(() => localStorage.getItem("auth_token"));
    expect(token).toBeTruthy();
    await expect
      .poll(
        async () => {
          try {
            const response = await page.request.get(
              "/api/v1/monitors/pipelines/catalog",
              {
                headers: { Authorization: `Bearer ${token}` },
                timeout: 5_000,
              },
            );
            if (!response.ok()) return `HTTP ${response.status()}`;
            const catalog = (await response.json()) as PipelineCatalog;
            return catalog.authoring_enabled ? "enabled" : "disabled";
          } catch {
            return "unavailable";
          }
        },
        {
          timeout: 30_000,
          intervals: [500, 1_000, 2_000],
          message: "Pipeline authoring catalog is ready after service startup",
        },
      )
      .toBe("enabled");
  });
  for (const strategy of ["adaptive_stream", "static_baseline"] as const)
    test(`builds, runs and inspects a branched ${strategy} pipeline`, async ({
      page,
      playwright,
    }, testInfo) => {
      const deviceId = randomUUID();
      const entityId = fixtureEntityId(deviceId);
      let serviceId: string | undefined;
      const serviceIds: string[] = [];
      const activationIds: string[] = [];
      let failed = false;
      let cleanupError: unknown;
      let pipelineId: string | undefined;
      let publisher: MqttClient | undefined;
      await page.goto("/");
      const token = await page.evaluate(() =>
        localStorage.getItem("auth_token"),
      );
      expect(token).toBeTruthy();
      const headers = { Authorization: `Bearer ${token}` };
      const api = await playwright.request.newContext({
        baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
        timeout: 210_000,
      });
      try {
        const catalogResponse = await api.get(
          "/api/v1/monitors/pipelines/catalog",
          { headers },
        );
        expect(catalogResponse.ok(), await catalogResponse.text()).toBeTruthy();
        const catalog = (await catalogResponse.json()) as PipelineCatalog;
        expect(
          catalog.authoring_enabled,
          "This dedicated lane requires pipeline_authoring_enabled=true",
        ).toBe(true);
        const topics = await addTestCharger(api, token!, deviceId, deviceId, [
          "voltage",
          "current",
          "temperature",
        ]);
        publisher = await connectAsync(
          process.env.MQTT_INGRESS_URL ?? "mqtt://127.0.0.1:1883",
          { ...ingressOptions(), clientId: `pipeline-e2e-${deviceId}` },
        );
        await page.setViewportSize({ width: 1600, height: 1100 });
        await page.goto(`/?create=monitoring&target=${entityId}`);
        await expect(
          page.getByRole("region", { name: "Pipeline library", exact: true }),
        ).toBeVisible();
        await page
          .getByRole("textbox", { name: "Pipeline name", exact: true })
          .fill(`Branched ${strategy} ${deviceId}`);
        await page
          .getByRole("radio", {
            name:
              strategy === "adaptive_stream"
                ? /Adaptive stream/
                : /Static baseline/,
          })
          .check();
        await page
          .getByRole("button", { name: "Create draft", exact: true })
          .click();
        await expect(
          page.getByRole("region", { name: "Pipeline editor", exact: true }),
        ).toBeVisible();
        pipelineId = new URL(page.url()).searchParams.get("pipeline")!;
        const createdResponse = await api.get(
          `/api/v1/monitors/pipelines/${pipelineId}`,
          { headers },
        );
        expect(createdResponse.ok(), await createdResponse.text()).toBeTruthy();
        const created = (await createdResponse.json()) as PipelineView;
        const slots = Object.fromEntries(
          created.draft.input_slots!.map((slot) => [slot.label, slot.id]),
        );
        await buildBranchedGraph(page, strategy === "adaptive_stream", slots);
        await page
          .getByRole("button", { name: "Save draft", exact: true })
          .click();
        await expect(
          page.getByText("Draft saved.", { exact: true }),
        ).toBeVisible();
        await page.reload();
        await expect(
          page.getByRole("combobox", {
            name: "Selected component",
            exact: true,
          }),
        ).toBeVisible();
        await selected(page).selectOption("features_merge_1");
        await expect(
          page.getByRole("heading", {
            name: "Incoming connections · output order",
            exact: true,
          }),
        ).toBeVisible();
        await page
          .getByRole("button", { name: "Publish revision", exact: true })
          .click();
        await expect(
          page.getByRole("button", { name: "Start revision", exact: true }),
        ).toBeVisible();
        await page
          .getByRole("button", { name: "Start revision", exact: true })
          .click();
        for (const name of ["voltage", "current", "temperature"])
          await page
            .getByRole("combobox", {
              name: `${name} · unit unspecified`,
              exact: true,
            })
            .selectOption(`${deviceId}:${name}`);
        await page
          .getByRole("checkbox", { name: /I reviewed the input bindings/ })
          .check();
        await page
          .getByRole("link", {
            name: "Configure collection in Sources",
            exact: true,
          })
          .click();
        await expect(
          page.getByRole("main", { name: "Sources workspace", exact: true }),
        ).toBeVisible();
        await page
          .getByRole("link", { name: "Return to service setup", exact: true })
          .click();
        await expect(
          page.getByRole("region", {
            name: "Review pipeline activation",
            exact: true,
          }),
        ).toBeVisible();
        for (const name of ["voltage", "current", "temperature"])
          await expect(
            page.getByRole("combobox", {
              name: `${name} · unit unspecified`,
              exact: true,
            }),
          ).toHaveValue(`${deviceId}:${name}`);
        await expect(
          page.getByRole("checkbox", { name: /I reviewed the input bindings/ }),
        ).not.toBeChecked();
        await page
          .getByRole("checkbox", { name: /I reviewed the input bindings/ })
          .check();
        const activationResponse = page.waitForResponse(
          (response) =>
            response.url().endsWith("/v1/monitors/pipeline-activations") &&
            response.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Start revision", exact: true })
          .last()
          .click();
        const response = await activationResponse;
        expect(response.ok(), await response.text()).toBeTruthy();
        const activation = (await response.json()) as PipelineActivationView;
        activationIds.push(activation.id);
        serviceId = activation.service_id;
        serviceIds.push(serviceId);
        const serviceDetails = page.getByRole("region", {
          name: "Monitoring service details",
          exact: true,
        });
        const activationError = page.locator('.pl-activation [role="alert"]');
        await Promise.race([
          serviceDetails.waitFor({ state: "visible", timeout: 240_000 }),
          activationError
            .first()
            .waitFor({ state: "visible", timeout: 240_000 })
            .then(async () => {
              throw new Error(
                (await activationError.first().textContent()) ??
                  "Pipeline activation failed",
              );
            }),
        ]);
        await publishSamples(publisher, topics, 65);
        const readState = async () => {
          const result = await api.get(
            `/api/v1/monitors/workspace?selected_service_id=${serviceId}`,
            { headers },
          );
          expect(result.ok(), await result.text()).toBeTruthy();
          return result.json() as Promise<PipelineWorkspace>;
        };
        const readHealth = async () => {
          const state = await readState();
          const status = state.services.find((item) => item.id === serviceId)
            ?.operational_status as OperationalStatus | undefined;
          return {
            stage: status?.stage,
            hasGaps: status?.coverage?.has_gaps,
            duplicateObservations:
              status?.coverage?.dropped_by_reason.observation_duplicate ?? 0,
            detail: status?.detail,
            droppedByReason: status?.coverage?.dropped_by_reason,
          };
        };
        await expect
          .poll(
            async () => {
              await publishSamples(publisher!, topics, 3);
              return readHealth();
            },
            {
              timeout: 120_000,
              intervals: [2_000, 3_000],
              message:
                "Monitor must be operational with complete coverage and zero duplicate observations",
            },
          )
          .toMatchObject({
            stage: "operational",
            hasGaps: false,
            duplicateObservations: 0,
          });
        await publishSamples(publisher, topics, 10);
        await expect
          .poll(
            async () => {
              await publishSamples(publisher!, topics, 3);
              const state = (await readState())
                .pipeline_state as unknown as PipelineState;
              return state?.observation?.passes.score.features_select_2?.output;
            },
            {
              timeout: 30_000,
              intervals: [1_000],
            },
          )
          .toBeTruthy();
        const runtime = (await readState())
          .pipeline_state as unknown as PipelineState;
        await testInfo.attach(`${strategy}-runtime`, {
          body: JSON.stringify(runtime, null, 2),
          contentType: "application/json",
        });
        const raw = runtime.observation?.passes.score.features_select_2;
        expect(raw?.output).toBeTruthy();
        if (raw && typeof raw.output === "object")
          expect(raw.output?.[slots.temperature!]).toBe(
            raw.input?.[slots.temperature!],
          );
        await page.getByRole("tab", { name: "Pipeline", exact: true }).click();
        await expect(
          page.getByRole("region", { name: "Running pipeline", exact: true }),
        ).toBeVisible();
        await selected(page).selectOption("features_select_2");
        await expect(
          page.getByRole("region", {
            name: "Live component diagnostics",
            exact: true,
          }),
        ).toContainText("Sampled observation", { timeout: 30_000 });
        if (strategy === "adaptive_stream") {
          expect(runtime.adaptive_learning?.model_updates).toBeGreaterThan(0);
          expect(
            runtime.nodes.features_select_2?.learned_updates,
          ).toBeGreaterThan(0);
          await expect(
            page.getByRole("region", {
              name: "Adaptive learning progress",
              exact: true,
            }),
          ).toContainText("Total detector updates");
          await expect(
            page.getByRole("region", {
              name: "Live component diagnostics",
              exact: true,
            }),
          ).toContainText("Successful learning updates");
        } else {
          expect(runtime.batch_training?.frozen).toBe(true);
          await expect(
            page.getByRole("region", {
              name: "Static fitting progress",
              exact: true,
            }),
          ).toContainText("Fitted baseline frozen");
        }
        await page
          .getByRole("button", { name: "Adjust arrangement", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Arrange automatically", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Save arrangement", exact: true })
          .click();
        const beforeLayout = runtime.run_id;
        expect(
          ((await readState()).pipeline_state as unknown as PipelineState)
            .run_id,
        ).toBe(beforeLayout);
        await page.screenshot({
          path: testInfo.outputPath(`${strategy}-live-pipeline.png`),
          fullPage: true,
        });
        await page.setViewportSize({ width: 390, height: 844 });
        await expect(
          page.getByRole("combobox", {
            name: "Selected component",
            exact: true,
          }),
        ).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        await page.screenshot({
          path: testInfo.outputPath(`${strategy}-mobile-pipeline.png`),
          fullPage: true,
        });
        if (strategy === "adaptive_stream") {
          const predecessorRun = runtime.run_id;
          const predecessorService = serviceId;
          await page.setViewportSize({ width: 1600, height: 1100 });
          await page
            .getByRole("button", { name: "Edit design", exact: true })
            .click();
          await page
            .getByRole("button", { name: "Open shared draft", exact: true })
            .click();
          await expect(
            page.getByRole("region", { name: "Pipeline editor", exact: true }),
          ).toBeVisible();
          await page
            .getByText("Input slots and learning settings", { exact: true })
            .click();
          await page
            .getByRole("spinbutton", {
              name: "Calibration observations",
              exact: true,
            })
            .fill("9");
          await page
            .getByRole("button", { name: "Publish revision", exact: true })
            .click();
          await expect(page.getByText(/Revision 2 published/)).toBeVisible();
          await page
            .getByRole("button", { name: "Review replacement", exact: true })
            .click();
          await expect(
            page.getByRole("region", {
              name: "Review pipeline activation",
              exact: true,
            }),
          ).toContainText("Learning or calibration settings changed");
          for (const name of ["voltage", "current", "temperature"])
            await expect(
              page.getByRole("combobox", {
                name: `${name} · unit unspecified`,
                exact: true,
              }),
            ).toHaveValue(`${deviceId}:${name}`);
          await page
            .getByRole("checkbox", {
              name: /I reviewed the input bindings and the interruption/,
            })
            .check();
          const replacementResponse = page.waitForResponse(
            (response) =>
              response.url().endsWith("/v1/monitors/pipeline-activations") &&
              response.request().method() === "POST",
          );
          await page
            .getByRole("button", { name: "Activate replacement", exact: true })
            .click();
          const replacementResult = await replacementResponse;
          expect(
            replacementResult.ok(),
            await replacementResult.text(),
          ).toBeTruthy();
          const replacement =
            (await replacementResult.json()) as PipelineActivationView;
          activationIds.push(replacement.id);
          expect(replacement.predecessor_service_id).toBe(predecessorService);
          serviceId = replacement.service_id;
          serviceIds.push(serviceId);
          await Promise.race([
            serviceDetails.waitFor({ state: "visible", timeout: 240_000 }),
            activationError
              .first()
              .waitFor({ state: "visible", timeout: 240_000 })
              .then(async () => {
                throw new Error(
                  (await activationError.first().textContent()) ??
                    "Replacement failed",
                );
              }),
          ]);
          await publishSamples(publisher, topics, 65);
          await expect
            .poll(
              async () => {
                await publishSamples(publisher!, topics, 3);
                return readHealth();
              },
              {
                timeout: 120_000,
                intervals: [2_000, 3_000],
                message:
                  "Monitor must be operational with complete coverage and zero duplicate observations",
              },
            )
            .toMatchObject({
              stage: "operational",
              hasGaps: false,
              duplicateObservations: 0,
            });
          const successor = (await readState())
            .pipeline_state as unknown as PipelineState;
          expect(successor.run_id).not.toBe(predecessorRun);
          await page
            .getByRole("tab", { name: "Pipeline", exact: true })
            .click();
          await page.getByText(/Linked monitoring history/).click();
          await expect(
            page.getByRole("link", { name: predecessorRun, exact: true }),
          ).toBeVisible();
          await page
            .getByRole("link", { name: predecessorRun, exact: true })
            .click();
          await expect(
            page.getByRole("region", { name: "Running pipeline", exact: true }),
          ).toContainText(predecessorRun);
          await testInfo.attach("replacement-run-identities", {
            body: JSON.stringify({
              predecessorRun,
              successorRun: successor.run_id,
              predecessorService,
              successorService: serviceId,
            }),
            contentType: "application/json",
          });
        }
      } catch (reason) {
        failed = true;
        throw reason;
      } finally {
        try {
          for (const id of activationIds) {
            const operation = await api.get(
              `/api/v1/monitors/pipeline-activations/${id}`,
              { headers },
            );
            if (
              operation.ok() &&
              !["succeeded", "failed", "cancelled"].includes(
                ((await operation.json()) as PipelineActivationView).phase,
              )
            ) {
              await api.delete(`/api/v1/monitors/pipeline-activations/${id}`, {
                headers,
              });
              await expect
                .poll(
                  async () => {
                    const current = await api.get(
                      `/api/v1/monitors/pipeline-activations/${id}`,
                      { headers },
                    );
                    return current.ok()
                      ? ((await current.json()) as PipelineActivationView).phase
                      : "unavailable";
                  },
                  { timeout: 120_000, intervals: [1000, 3000] },
                )
                .toMatch(/^(succeeded|failed|cancelled)$/);
            }
          }
          if (serviceId) {
            const snapshot = await api.get(
              `/api/v1/monitors/workspace?selected_service_id=${serviceId}`,
              { headers },
            );
            if (snapshot.ok())
              await testInfo.attach(`${strategy}-final-workspace`, {
                body: await snapshot.body(),
                contentType: "application/json",
              });
          }
          for (const id of new Set(serviceIds))
            await api.delete(`/api/v1/monitors/${id}`, { headers });
          if (pipelineId) {
            const result = await api.get(
              `/api/v1/monitors/pipelines/${pipelineId}`,
              { headers },
            );
            if (result.ok()) {
              const pipeline = (await result.json()) as PipelineView;
              await api.patch(`/api/v1/monitors/pipelines/${pipelineId}`, {
                headers,
                data: {
                  expected_version: pipeline.version,
                  name: pipeline.name,
                  description: pipeline.description,
                  archived: true,
                },
              });
            }
          }
          await publisher?.endAsync();
          await removeTestCharger(api, token!, deviceId);
        } catch (reason) {
          if (!failed) cleanupError = reason;
          await testInfo.attach("cleanup-error", {
            body: String(reason),
            contentType: "text/plain",
          });
        }
        await api.dispose();
      }
      if (cleanupError) throw cleanupError;
    });

  test("keeps the maximum graph editable with keyboard controls, dark mode and mobile layout", async ({
    page,
    playwright,
  }, testInfo) => {
    await page.goto("/");
    const token = await page.evaluate(() => localStorage.getItem("auth_token"));
    const headers = { Authorization: `Bearer ${token}` };
    const api = await playwright.request.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    });
    let pipelineId: string | undefined;
    let copyId: string | undefined;
    try {
      const result = await api.get("/api/v1/monitors/pipelines/catalog", {
        headers,
      });
      expect(result.ok(), await result.text()).toBeTruthy();
      const catalog = (await result.json()) as PipelineCatalog;
      expect(catalog.authoring_enabled).toBe(true);
      const template = catalog.templates.find(
        (item) => item.definition.strategy === "adaptive_stream",
      )!;
      const definition = structuredClone(template.definition);
      definition.input_slots = Array.from({ length: 100 }, (_item, index) => ({
        id: `slot_${String(index).padStart(3, "0")}_${"x".repeat(55)}`,
        label: `Input ${index + 1}`,
      }));
      const chain = Array.from({ length: 60 }, (_item, index) => ({
        id: processingId(index + 1),
        kind: "transform" as const,
        component: "adaptive.random_projection",
        params: { n_components: 100 },
      }));
      definition.nodes!.push(...chain);
      definition.edges = definition.edges!.filter(
        (edge) => edge.target !== "detector",
      );
      const ids = ["input", ...chain.map((node) => node.id), "detector"];
      definition.edges.push(
        ...ids
          .slice(1)
          .map((target, index) => ({ source: ids[index]!, target, order: 0 })),
      );
      const createdResponse = await api.post("/api/v1/monitors/pipelines", {
        headers,
        data: {
          name: `Maximum graph ${randomUUID()}`,
          definition,
          layout: {
            nodes: Object.fromEntries(
              definition.nodes!.map((node, index) => [
                node.id,
                {
                  x: (index % 8) * 250,
                  y: Math.floor(index / 8) * 150,
                  label: `Step ${index + 1}`,
                },
              ]),
            ),
          },
        },
      });
      expect(createdResponse.ok(), await createdResponse.text()).toBeTruthy();
      const created = (await createdResponse.json()) as PipelineView;
      pipelineId = created.id;
      const focusedResponse = await api.post(
        `/api/v1/monitors/pipelines/${pipelineId}/validate`,
        { headers, data: { definition, selected_node_id: processingId(59) } },
      );
      expect(focusedResponse.ok(), await focusedResponse.text()).toBeTruthy();
      const reportBytes = (await focusedResponse.body()).byteLength;
      expect(reportBytes).toBeLessThanOrEqual(512 * 1024);
      const report = (await focusedResponse.json()) as PipelineValidationReport;
      expect(report.valid).toBe(true);
      expect(report.selected_node_id).toBe(processingId(59));
      expect(report.provenance_complete).toBe(false);
      const outputNames = report.features![processingId(59)]!.map(
        (feature) => feature.name,
      );
      expect(outputNames).toHaveLength(100);
      definition.nodes = definition.nodes!.map((node) =>
        node.id === processingId(60)
          ? {
              ...node,
              component: "features.select",
              params: { features: outputNames },
            }
          : node,
      );
      const selectedDefinition = await api.put(
        `/api/v1/monitors/pipelines/${pipelineId}/draft`,
        {
          headers,
          data: {
            expected_version: created.version,
            definition,
            layout: created.layout,
          },
        },
      );
      expect(
        selectedDefinition.ok(),
        await selectedDefinition.text(),
      ).toBeTruthy();
      await page.setViewportSize({ width: 1600, height: 1100 });
      await page.goto(`/?pipeline=${pipelineId}`);
      await expect(selected(page)).toBeVisible();
      await selected(page).focus();
      await page.keyboard.press("End");
      await page.keyboard.press("Enter");
      await expect(
        page.getByRole("textbox", { name: "Node title", exact: true }),
      ).toBeVisible();
      await page
        .locator(`.react-flow__node[data-id="${processingId(60)}"]`)
        .focus();
      await page.keyboard.press("Delete");
      await expect(page.locator(".react-flow__node")).toHaveCount(63);
      await page
        .getByRole("button", { name: "Undo graph change", exact: true })
        .click();
      await expect(page.locator(".react-flow__node")).toHaveCount(64);
      await expect(
        page.getByRole("heading", { name: "Output features", exact: true }),
      ).toBeVisible();
      await expect(
        page.locator('.pl-inspector input[type="checkbox"]'),
      ).toHaveCount(100);
      await expect(
        page.getByRole("checkbox", { name: outputNames[99]!, exact: true }),
      ).toBeChecked();
      await expect(page.locator(".pl-lineage > li")).toHaveCount(100);
      await expect(
        page.getByText(/Some source provenance is omitted/),
      ).toBeVisible();
      const profiler = await page.context().newCDPSession(page);
      await profiler.send("HeapProfiler.collectGarbage");
      const heapBefore = await profiler.send("Runtime.getHeapUsage");
      const interactions = await page.evaluate(
        async (identifiers) => {
          const selector = document.querySelector<HTMLSelectElement>(
            '[aria-label="Component inspector"] select',
          )!;
          const durations: number[] = [];
          for (let index = 0; index < 40; index++) {
            const start = performance.now();
            selector.value = identifiers[index]!;
            selector.dispatchEvent(new Event("change", { bubbles: true }));
            await new Promise<void>((done) =>
              requestAnimationFrame(() => done()),
            );
            durations.push(performance.now() - start);
          }
          return {
            maximumInteractionMs: Math.max(...durations),
            nodeCount: document.querySelectorAll(".react-flow__node").length,
          };
        },
        chain.slice(0, 40).map((node) => node.id),
      );
      await expect(page.locator(".pl-lineage > li").first()).toContainText(
        processingId(40),
      );
      await expect(page.locator(".pl-lineage > li")).toHaveCount(100);
      await profiler.send("HeapProfiler.collectGarbage");
      const heapAfter = await profiler.send("Runtime.getHeapUsage");
      const metrics = {
        ...interactions,
        featureCount: 100,
        inputSlotIdLength: 64,
        nodeIdLength: 64,
        focusedReportBytes: reportBytes,
        retainedHeapGrowthBytes: heapAfter.usedSize - heapBefore.usedSize,
      };
      await profiler.detach();
      const metricsPath = testInfo.outputPath("maximum-graph-metrics.json");
      await writeFile(metricsPath, JSON.stringify(metrics, null, 2));
      await testInfo.attach("maximum-graph-metrics", {
        path: metricsPath,
        contentType: "application/json",
      });
      expect(metrics.nodeCount).toBe(64);
      expect(metrics.maximumInteractionMs).toBeLessThan(500);
      expect(metrics.retainedHeapGrowthBytes).toBeLessThan(32 * 1024 * 1024);
      await page
        .getByRole("button", { name: "Application menu", exact: true })
        .click();
      await page
        .getByRole("menuitem", { name: "Settings", exact: true })
        .click();
      await page.getByRole("radio", { name: "Dark", exact: true }).check();
      await page
        .getByRole("button", { name: "Close settings", exact: true })
        .click();
      await page.screenshot({
        path: testInfo.outputPath("maximum-graph-dark.png"),
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page
        .getByRole("button", { name: "inspector", exact: true })
        .click();
      await selected(page).selectOption(processingId(60));
      await expect(
        page.locator('.pl-inspector input[type="checkbox"]'),
      ).toHaveCount(100);
      await page
        .getByRole("textbox", { name: "Node title", exact: true })
        .fill("Keyboard and mobile inspection");
      await page
        .getByRole("button", { name: "Save draft", exact: true })
        .click();
      await expect(
        page.getByText("Draft saved.", { exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await selected(page).scrollIntoViewIfNeeded();
      await page.screenshot({
        path: testInfo.outputPath("maximum-graph-mobile.png"),
        fullPage: true,
      });
      const beforeConflict = await api.get(
        `/api/v1/monitors/pipelines/${pipelineId}`,
        { headers },
      );
      const shared = (await beforeConflict.json()) as PipelineView;
      const collaborator = await api.patch(
        `/api/v1/monitors/pipelines/${pipelineId}`,
        {
          headers,
          data: {
            expected_version: shared.version,
            name: `${shared.name} updated`,
            description: shared.description,
            archived: false,
          },
        },
      );
      expect(collaborator.ok(), await collaborator.text()).toBeTruthy();
      await page
        .getByRole("textbox", { name: "Node title", exact: true })
        .fill("Preserved conflicted edit");
      await page
        .getByRole("button", { name: "Save draft", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Draft conflict", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("textbox", { name: "Node title", exact: true }),
      ).toHaveValue("Preserved conflicted edit");
      await page
        .getByRole("button", { name: "Save as a new design", exact: true })
        .click();
      await expect
        .poll(() => new URL(page.url()).searchParams.get("pipeline"))
        .not.toBe(pipelineId);
      copyId = new URL(page.url()).searchParams.get("pipeline")!;
      const copyResponse = await api.get(
        `/api/v1/monitors/pipelines/${copyId}`,
        { headers },
      );
      expect(copyResponse.ok(), await copyResponse.text()).toBeTruthy();
      const copy = (await copyResponse.json()) as PipelineView;
      expect(copy.layout.nodes?.[processingId(60)]?.label).toBe(
        "Preserved conflicted edit",
      );
      expect(copy.draft.nodes).toHaveLength(64);
    } finally {
      if (copyId) {
        const response = await api.get(`/api/v1/monitors/pipelines/${copyId}`, {
          headers,
        });
        if (response.ok()) {
          const copy = (await response.json()) as PipelineView;
          await api.patch(`/api/v1/monitors/pipelines/${copyId}`, {
            headers,
            data: {
              expected_version: copy.version,
              name: copy.name,
              archived: true,
            },
          });
        }
      }
      if (pipelineId) {
        const response = await api.get(
          `/api/v1/monitors/pipelines/${pipelineId}`,
          { headers },
        );
        if (response.ok()) {
          const pipeline = (await response.json()) as PipelineView;
          await api.patch(`/api/v1/monitors/pipelines/${pipelineId}`, {
            headers,
            data: {
              expected_version: pipeline.version,
              name: pipeline.name,
              archived: true,
            },
          });
        }
      }
      await api.dispose();
    }
  });
});
