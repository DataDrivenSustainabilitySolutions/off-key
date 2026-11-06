import type { DetectorInputSeries } from "./detector-inputs";

export type ChartSampleSource = {
  id: string;
  name: string;
  unit?: string | null;
  points: readonly (readonly [timestamp: number, value: number | null])[];
  valueType?: "number" | "boolean" | "alarm";
};

export const detectorInputSamples = (inputs: readonly DetectorInputSeries[] = []): ChartSampleSource[] =>
  inputs.map(input => ({ id: input.id, name: `Detector input · ${input.name}`, points: input.data }));
