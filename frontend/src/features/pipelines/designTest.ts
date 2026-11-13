import { createContext, type ComponentType } from "react";
import type { PipelineDefinition } from "./contracts";

/** What a test of a design is told about the composer it sits in. */
export type DesignTestProps = {
  /** Names the composer, so that a test under way is found again after a detour. */
  session: string;
  definition: PipelineDefinition;
  /** The reading each input monitors, by slot. */
  readings: Record<string, string | undefined>;
  /** The service's name. */
  name: string;
  /** The entity the readings belong to. */
  scope?: string;
  /** Why the design cannot run yet, in a sentence. */
  blocked?: string;
  onChooseReadings: () => void;
};

/** A test a design came with, such as the one it was proposed with. */
export type DesignEvidence = {
  /** Names the test where the tests are kept. */
  run: string;
  /** Who ran it. */
  by: string;
  /** The design as it came, to tell when it has been changed since. */
  definition: PipelineDefinition;
};

export type DesignTestStatusProps = {
  session: string;
  /** Whether the panel is on screen. */
  open: boolean;
  /** Shown as the design's test until the member runs one. */
  evidence?: DesignEvidence;
};

export type DesignTestValuesProps = {
  session: string;
  /** The step whose values are shown. */
  node: string;
  definition: PipelineDefinition;
  /** Opens the test, for a design that has none to show yet. */
  onOpenTest: () => void;
};

/** A way to try a design before it monitors anything. The composer shows it without knowing how it works;
 * the screen that mounts the composer provides it. */
export type DesignTest = {
  /** Runs a test and shows what it found, docked beside the canvas. */
  Panel: ComponentType<DesignTestProps>;
  /** The words on the button that opens the panel. It stays mounted while the composer is. */
  Status: ComponentType<DesignTestStatusProps>;
  /** What went into one step and came out of it in the last test, with the step's settings. */
  Values: ComponentType<DesignTestValuesProps>;
};

export const DesignTestContext = createContext<DesignTest | undefined>(undefined);
