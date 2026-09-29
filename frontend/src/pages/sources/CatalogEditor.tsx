import { useState } from "react";
import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type {
  Catalog,
  CatalogCharger,
  CatalogSnapshot,
  CatalogSource,
} from "@/types/collection";
import { catalogView, type CatalogFilter } from "@/lib/catalog-view";
import { pausedPolicy } from "@/types/collection";
import { InlineField } from "./InlineField";
import { ChargerEditor } from "./ChargerEditor";

const newCharger = (chargers: CatalogCharger[] = []): CatalogCharger => {
  let localId = 0;
  while (chargers.some((charger) => charger.local_id === String(localId)))
    localId += 1;
  return {
    id: crypto.randomUUID(),
    local_id: String(localId),
    label: "New charger",
    policy: pausedPolicy,
    sensors: [],
  };
};

export function CatalogEditor({
  catalog,
  snapshot,
  disabled,
  onChange,
  filter,
  showAll,
  selected,
  onSelect,
}: {
  catalog: Catalog;
  snapshot: CatalogSnapshot;
  disabled: boolean;
  onChange: (catalog: Catalog) => void;
  filter: CatalogFilter;
  showAll: () => void;
  selected: ReadonlySet<string>;
  onSelect: (ids: string[], checked: boolean) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const visible = catalogView(catalog, filter);
  const editSource = (source: CatalogSource) =>
    onChange({
      ...catalog,
      sources: catalog.sources.map((item) =>
        item.id === source.id ? source : item,
      ),
    });
  const addBroker = () => {
    const source: CatalogSource = {
      id: crypto.randomUUID(),
      label: "New broker",
      host: "",
      port: 1883,
      verified: false,
      forward_port: null,
      chargers: [],
    };
    showAll();
    setExpanded((current) => new Set(current).add(source.id));
    onChange({ ...catalog, sources: [...catalog.sources, source] });
  };

  return (
    <div className="space-y-3">
      <Button variant="outline" disabled={disabled} onClick={addBroker}>
        Add broker
      </Button>
      {visible.length === 0 && catalog.sources.length > 0 && (
        <p className="text-sm text-muted-foreground">
          No matches. Change or clear the filters.
        </p>
      )}
      {visible.map(({ source, chargers }) => {
        const open = expanded.has(source.id);
        const saved = snapshot.catalog.sources.find(
          (item) => item.id === source.id,
        );
        const metadata = (patch: Partial<CatalogSource>) => {
          showAll();
          editSource({ ...source, ...patch });
        };
        const state = snapshot.ingress.sources?.[source.id];
        return (
          <section
            key={source.id}
            aria-label={`Broker ${source.label}`}
            className="rounded-xl border bg-card"
          >
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3 sm:p-4">
              <div className="min-w-0 flex-1 basis-48 font-semibold">
                <InlineField
                  label="Broker name"
                  value={source.label}
                  maxLength={120}
                  disabled={disabled}
                  onChange={(label) => metadata({ label })}
                />
                <div className="ml-2 flex flex-wrap items-center gap-2 text-xs font-normal text-muted-foreground">
                  <span>{state?.status ?? "Not configured"}</span>
                  <span>· {source.verified ? "Observed" : "Candidate"}</span>
                  {JSON.stringify(source) !== JSON.stringify(saved) && (
                    <span className="text-amber-700 dark:text-amber-300">
                      · Unsaved changes
                    </span>
                  )}
                </div>
              </div>
              <div className="min-w-0 basis-48 text-sm">
                <span className="ml-2 text-xs text-muted-foreground">
                  Hostname
                </span>
                <InlineField
                  label="Hostname"
                  value={source.host}
                  maxLength={253}
                  placeholder="Add hostname"
                  disabled={disabled}
                  onChange={(host) => metadata({ host, verified: false })}
                  onCancel={() => editSource(source)}
                />
              </div>
              <div className="w-24 text-sm">
                <span className="ml-2 text-xs text-muted-foreground">Port</span>
                <InlineField
                  label="Port"
                  value={source.port ? String(source.port) : ""}
                  type="number"
                  min={1}
                  max={65535}
                  disabled={disabled}
                  onChange={(port) =>
                    metadata({ port: Number(port), verified: false })
                  }
                  onCancel={() => editSource(source)}
                />
              </div>
              <Button
                variant="ghost"
                aria-label={`${open ? "Hide" : "Show"} chargers for ${source.label}`}
                aria-expanded={open}
                aria-controls={`broker-${source.id}`}
                onClick={() =>
                  setExpanded((current) => {
                    const next = new Set(current);
                    if (open) next.delete(source.id);
                    else next.add(source.id);
                    return next;
                  })
                }
              >
                {open ? <ChevronDown /> : <ChevronRight />}
                {source.chargers.length}{" "}
                {source.chargers.length === 1 ? "charger" : "chargers"}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Actions for broker ${source.label}`}
                    disabled={disabled}
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() =>
                      onChange({
                        ...catalog,
                        sources: catalog.sources.filter(
                          (item) => item.id !== source.id,
                        ),
                      })
                    }
                  >
                    Remove broker
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            {state?.error && (
              <p role="alert" className="px-5 pb-3 text-sm text-destructive">
                {state.error}
              </p>
            )}
            {open && (
              <div
                id={`broker-${source.id}`}
                className="space-y-3 border-t bg-muted/10 p-3 sm:p-4"
              >
                {chargers.map((charger) => (
                  <ChargerEditor
                    key={charger.id}
                    catalog={catalog}
                    source={source}
                    charger={charger}
                    saved={saved?.chargers.find(
                      (item) => item.id === charger.id,
                    )}
                    disabled={disabled}
                    filter={filter}
                    showAll={showAll}
                    selected={selected}
                    onSelect={onSelect}
                    onChange={(next) =>
                      editSource({
                        ...source,
                        chargers: source.chargers.map((item) =>
                          item.id === charger.id ? next : item,
                        ),
                      })
                    }
                    onRemove={() =>
                      editSource({
                        ...source,
                        chargers: source.chargers.filter(
                          (item) => item.id !== charger.id,
                        ),
                      })
                    }
                  />
                ))}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={disabled}
                  onClick={() => {
                    showAll();
                    editSource({
                      ...source,
                      chargers: [
                        ...source.chargers,
                        newCharger(source.chargers),
                      ],
                    });
                  }}
                >
                  Add charger
                </Button>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
