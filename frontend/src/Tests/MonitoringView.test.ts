// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  chooseTab, createPipeline, dropReplacement, editFromRun, monitoringNavigationKey, openPipeline, resetView,
  setActivation, setRevision, showLibrary,
} from "@/domain/monitoring/monitoringView";

const search = (query: string) => new URLSearchParams(query);

describe("monitoring URL contract", () => {
  it.each([
    ["resetView keeps unrelated keys and the selected source",
      () => resetView(search("pipeline=p&revision=r&service=s&from=x&keep=1"), "src", { create: "monitoring", reading: undefined }),
      "keep=1&source=src&create=monitoring"],
    ["resetView without a selection leaves an existing source alone",
      () => resetView(search("source=old&tab=pipeline&stream=s")), "source=old"],
    ["openPipeline from the library leaves creation",
      () => openPipeline(search("view=pipelines&create=monitoring&revision=r&activation=a"), "p1"), "pipeline=p1"],
    ["openPipeline during creation keeps creation and sets the target",
      () => openPipeline(search("create=monitoring&revision=r"), "p1", "t1"), "create=monitoring&pipeline=p1&target=t1"],
    ["createPipeline clears the editor and its predecessor",
      () => createPipeline(search("pipeline=p&revision=r&activation=a&view=pipelines&replace=x&from=y&target=t")),
      "target=t&create=monitoring"],
    ["showLibrary keeps from and create",
      () => showLibrary(search("pipeline=p&revision=r&activation=a&replace=x&from=y&create=monitoring")),
      "from=y&create=monitoring&view=pipelines"],
    ["setRevision replaces the revision and forgets the activation",
      () => setRevision(search("pipeline=p&revision=old&activation=a"), "new"), "pipeline=p&revision=new"],
    ["setRevision without one clears it",
      () => setRevision(search("pipeline=p&revision=old&activation=a")), "pipeline=p"],
    ["setActivation tracks an operation",
      () => setActivation(search("pipeline=p"), "op"), "pipeline=p&activation=op"],
    ["dropReplacement starts a new service instead",
      () => dropReplacement(search("pipeline=design&revision=published&replace=previous")), "pipeline=design&revision=published"],
    ["editFromRun replaces a replaceable service",
      () => editFromRun(search("service=s1&tab=pipeline&pipeline=p&revision=r&activation=a&view=pipelines"), "s1", true),
      "view=pipelines&create=monitoring&replace=s1"],
    ["editFromRun copies a retained run",
      () => editFromRun(search("service=s1&tab=pipeline"), "s1", false), "create=monitoring&from=s1"],
    ["chooseTab keeps the evidence stream",
      () => chooseTab(search("service=s&stream=a"), "evidence"), "service=s&stream=a&tab=evidence"],
    ["chooseTab drops the stream elsewhere",
      () => chooseTab(search("service=s&stream=a"), "overview"), "service=s&tab=overview"],
    ["chooseTab sets a given stream",
      () => chooseTab(search("service=s"), "overview", "b"), "service=s&tab=overview&stream=b"],
  ])("%s", (_, transition, expected) => {
    expect(transition().toString()).toBe(expected);
  });

  it("never mutates its input", () => {
    const params = search("pipeline=p&revision=r");
    setRevision(params);
    expect(params.toString()).toBe("pipeline=p&revision=r");
  });

  it("names the remembered workspace URL per account", () => {
    expect(monitoringNavigationKey("u1")).toBe("monitoring:u1:url");
  });
});
