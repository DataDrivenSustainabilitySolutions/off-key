/**
 * PreprocessingSection Component
 *
 * Manages the preprocessing pipeline configuration for anomaly detection.
 * Allows adding, removing, and reordering preprocessing steps.
 */

import React from "react";
import { Button } from "@/components/ui/button";
import { ChevronUp, ChevronDown } from "lucide-react";
import type {
  PreprocessingStepConfig,
  PreprocessorDefinition,
  ParameterSchema,
} from "@/types/monitoring";

// Helper function to parse numeric input
const parseNumericInput = (
  rawValue: string,
  schemaType?: string
): string | number => {
  if (rawValue === "") return "";

  if (schemaType === "integer" || schemaType === "number") {
    const parsed =
      schemaType === "integer" ? parseInt(rawValue, 10) : parseFloat(rawValue);
    return Number.isNaN(parsed) ? "" : parsed;
  }

  return rawValue;
};

interface PreprocessingSectionProps {
  steps: PreprocessingStepConfig[];
  availablePreprocessors: Record<string, PreprocessorDefinition>;
  newPreprocessorType: string;
  isLoading: boolean;
  onSelectType: (type: string) => void;
  onAdd: () => void;
  onParamChange: (
    index: number,
    key: string,
    rawValue: string,
    schemaType?: string
  ) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
  onRemove: (index: number) => void;
}

export const PreprocessingSection: React.FC<PreprocessingSectionProps> = ({
  steps,
  availablePreprocessors,
  newPreprocessorType,
  isLoading,
  onSelectType,
  onAdd,
  onParamChange,
  onMoveUp,
  onMoveDown,
  onRemove,
}) => (
  <div className="mt-10">
    <div className="flex items-center justify-between mb-2">
      <h3 className="text-md font-semibold">Preprocessing (optional)</h3>
      {isLoading && <span className="text-xs text-gray-500">Loading...</span>}
    </div>

    <div className="flex gap-2 items-center mb-3">
      <select
        className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
        value={newPreprocessorType}
        onChange={(e) => onSelectType(e.target.value)}
        disabled={isLoading}
      >
        <option value="">Add step...</option>
        {Object.keys(availablePreprocessors).map((key) => (
          <option key={key} value={key}>
            {key}
          </option>
        ))}
      </select>
      <Button
        className="bg-indigo-800 hover:bg-indigo-700"
        disabled={!newPreprocessorType || isLoading}
        onClick={onAdd}
      >
        Add
      </Button>
    </div>

    {steps.length === 0 && (
      <p className="text-sm text-gray-500">No preprocessing steps selected.</p>
    )}

    <div className="space-y-4">
      {steps.map((step, index) => {
        const schemaProps: Record<string, ParameterSchema> =
          availablePreprocessors[step.type]?.parameters?.properties || {};

        return (
          <div
            key={step.id ?? `${step.type}-${index}`}
            className="border rounded p-3 bg-gray-50 dark:bg-neutral-900"
          >
            <div className="flex items-center justify-between">
              <div className="font-semibold">
                {index + 1}. {step.type}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onMoveUp(index)}
                  disabled={index === 0}
                  title="Move up"
                >
                  <ChevronUp className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onMoveDown(index)}
                  disabled={index === steps.length - 1}
                  title="Move down"
                >
                  <ChevronDown className="h-4 w-4" />
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => onRemove(index)}
                >
                  Remove
                </Button>
              </div>
            </div>

            <div className="mt-3 space-y-3">
              {Object.entries(schemaProps).length === 0 && (
                <p className="text-sm text-gray-500">No parameters.</p>
              )}
              {Object.entries(schemaProps).map(([key, schema]) => (
                <div key={key} className="flex flex-col">
                  <label className="text-sm font-medium mb-1">
                    {key}
                    {schema?.description && (
                      <span className="text-xs text-gray-500 ml-1">
                        ({schema.description})
                      </span>
                    )}
                  </label>
                  <input
                    type={
                      schema?.type === "integer" || schema?.type === "number"
                        ? "number"
                        : "text"
                    }
                    className="border rounded px-3 py-2 bg-white text-black dark:bg-neutral-900 dark:text-white"
                    value={step.params?.[key] ?? ""}
                    onChange={(e) =>
                      onParamChange(
                        index,
                        key,
                        e.target.value,
                        schema?.type
                      )
                    }
                    min={schema?.minimum}
                    max={schema?.maximum}
                    step="any"
                  />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  </div>
);

export { parseNumericInput };
export default PreprocessingSection;
