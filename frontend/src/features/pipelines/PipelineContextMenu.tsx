import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Menu, MenuItem } from "./contextMenu";

type Level = { menu: Menu; active: number; query: string };
const itemsOf = (level: Level) =>
  level.query && level.menu.search ? level.menu.search.results(level.query) : level.menu.items;

/** Room kept between a menu and the window edge. */
const EDGE = 8;

/**
 * A menu at the pointer that opens submenus beside it. Arrow keys, the mouse wheel and
 * the pointer move through the entries, typing narrows a searchable menu, Enter or a
 * click chooses, and Escape or Left closes one level.
 */
export function PipelineContextMenu({ x, y, menu, onClose }: {
  x: number;
  y: number;
  menu: Menu;
  onClose: (restoreFocus: boolean) => void;
}) {
  const id = useId();
  const [levels, setLevels] = useState<Level[]>([{ menu, active: 0, query: "" }]);
  const panels = useRef<(HTMLDivElement | null)[]>([]);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const root = useRef<HTMLDivElement>(null);
  const depth = levels.length - 1;
  const deepest = levels[depth]!;
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });

  // The pointer leaving the menu for anywhere else, or the window changing, closes it.
  useEffect(() => {
    const outside = (event: Event) => {
      if (!(event.target instanceof Node) || !root.current?.contains(event.target)) close.current(false);
    };
    const dismiss = () => close.current(false);
    window.addEventListener("pointerdown", outside, true);
    window.addEventListener("contextmenu", outside, true);
    window.addEventListener("resize", dismiss);
    window.addEventListener("blur", dismiss);
    return () => {
      window.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("contextmenu", outside, true);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("blur", dismiss);
    };
  }, []);

  // Each level opens beside the entry that opened it, turning back at the window's edge.
  // Placement needs each panel's measured size, so it is written to the panels directly.
  useLayoutEffect(() => {
    const room = { right: window.innerWidth - EDGE, bottom: window.innerHeight - EDGE };
    panels.current.slice(0, levels.length).forEach((panel, index) => {
      if (!panel) return;
      const { width, height } = panel.getBoundingClientRect();
      let left = x;
      let top = y;
      const parentPanel = index > 0 ? panels.current[index - 1] : undefined;
      if (parentPanel) {
        const parent = parentPanel.getBoundingClientRect();
        const opener = parentPanel.querySelector<HTMLElement>("[data-active='true']")?.getBoundingClientRect();
        left = parent.right - 4;
        if (left + width > room.right) left = parent.left - width + 4;
        top = (opener?.top ?? parent.top) - 5;
      } else if (left + width > room.right) left = x - width;
      panel.style.left = `${Math.max(EDGE, Math.min(left, room.right - width))}px`;
      panel.style.top = `${Math.max(EDGE, Math.min(top, room.bottom - height))}px`;
      panel.style.visibility = "visible";
    });
  }, [levels, x, y]);

  // Typing goes to the deepest searchable level; otherwise the menu itself keeps focus.
  // Closing a level can drop focus with the element that held it, so each change of depth restores it.
  const searchLevel = levels.map((level, index) => (level.menu.search ? index : -1)).filter((index) => index >= 0).pop();
  useEffect(() => {
    const target = searchLevel !== undefined ? inputs.current[searchLevel] : root.current;
    if (target && document.activeElement !== target) target.focus({ preventScroll: true });
  }, [searchLevel, depth]);

  useEffect(() => {
    panels.current[depth]?.querySelector("[data-active='true']")?.scrollIntoView?.({ block: "nearest" });
  }, [depth, deepest.active, deepest.query]);

  const update = (index: number, change: Partial<Level>, keep = index) =>
    setLevels((previous) => previous.slice(0, keep + 1).map((level, position) =>
      position === index ? { ...level, ...change } : level));
  /** Step the active entry; following the pointer or wheel also opens the submenu it lands on. */
  const intent = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(intent.current), []);
  const latest = useRef(levels);
  useEffect(() => { latest.current = levels; });
  const move = (index: number, step: number, follow = false) => {
    const level = latest.current[index];
    if (!level) return;
    const items = itemsOf(level);
    if (!items.length) return;
    const active = (level.active + step + items.length) % items.length;
    const item = items[active]!;
    if (follow && item.submenu && !item.blocked)
      setLevels((previous) => [...previous.slice(0, index), { ...previous[index]!, active },
        { menu: item.submenu!, active: 0, query: "" }]);
    else update(index, { active });
  };
  const open = (index: number, item: MenuItem) => {
    if (!item.submenu || item.blocked) return;
    setLevels((previous) => [...previous.slice(0, index + 1), { menu: item.submenu!, active: 0, query: "" }]);
  };
  const choose = (index: number, item: MenuItem) => {
    if (item.blocked) return;
    if (item.submenu) return open(index, item);
    onClose(false);
    item.run?.();
  };
  const keydown = (event: KeyboardEvent) => {
    const items = itemsOf(deepest);
    const item = items[deepest.active];
    const key = event.key;
    if (key === "ArrowDown" || key === "ArrowUp") move(depth, key === "ArrowDown" ? 1 : -1);
    else if (key === "Home" || key === "End") update(depth, { active: key === "Home" ? 0 : Math.max(0, items.length - 1) });
    else if (key === "ArrowRight" && item?.submenu) open(depth, item);
    else if (key === "Enter" && item) choose(depth, item);
    else if (key === "Escape" || (key === "ArrowLeft" && depth > 0)) {
      if (depth === 0) onClose(true);
      else setLevels((previous) => previous.slice(0, -1));
    } else if (key === "Tab") onClose(true);
    else return;
    event.preventDefault();
    event.stopPropagation();
  };

  return createPortal(<div ref={root} className="pl-context-menu" tabIndex={-1} onKeyDown={keydown}
    aria-activedescendant={searchLevel === undefined ? `${id}-${depth}-${deepest.active}` : undefined}
    onContextMenu={(event) => event.preventDefault()}>
    {levels.map((level, index) => {
      const items = itemsOf(level);
      const helpId = `${id}-${index}-help`;
      return <div key={`${index}:${level.menu.label}`} ref={(element) => { panels.current[index] = element; }}
        className="pl-context-panel" style={{ left: x, top: y, visibility: "hidden" }}
        onPointerEnter={() => { if (index > 0) window.clearTimeout(intent.current); }}
        onWheel={(event) => {
          // The wheel steps through the entries rather than scrolling past them.
          if (!event.deltaY) return;
          move(index, event.deltaY > 0 ? 1 : -1, true);
        }}>
        {index > 0 && <div className="pl-context-title">
          <button type="button" tabIndex={-1} aria-label={`Back from ${level.menu.label}`}
            onPointerDown={(event) => event.preventDefault()}
            onClick={() => setLevels((previous) => previous.slice(0, index))}><ChevronLeft size={14} aria-hidden="true" /></button>
          {level.menu.label}
        </div>}
        {level.menu.search && <input ref={(element) => { inputs.current[index] = element; }} type="search"
          className="pl-context-search" aria-label={level.menu.search.label} placeholder={`${level.menu.search.label}…`}
          value={level.query} autoComplete="off" spellCheck={false}
          aria-controls={`${id}-${index}`} aria-activedescendant={itemsOf(deepest).length ? `${id}-${depth}-${deepest.active}` : undefined}
          onChange={(event) => update(index, { query: event.target.value, active: 0 })} />}
        <ScrollLock>
          <div role="menu" id={`${id}-${index}`} aria-label={level.query ? `${level.menu.label}: matching steps` : level.menu.label}
            className="pl-context-list">
            {items.map((item, position) => {
              const active = position === level.active;
              const Icon = item.icon;
              const opened = levels[index + 1] && active && !!item.submenu;
              return <div key={item.key} role="presentation">
                {item.separated && <div role="separator" className="pl-context-separator" />}
                <div role="menuitem" id={`${id}-${index}-${position}`} data-active={active}
                  className={`pl-context-item${item.destructive ? " is-destructive" : ""}`}
                  aria-disabled={!!item.blocked || undefined} aria-haspopup={item.submenu ? "menu" : undefined}
                  aria-expanded={item.submenu ? !!opened : undefined} title={item.blocked}
                  aria-describedby={active && item.help ? helpId : undefined}
                  onPointerMove={() => {
                    window.clearTimeout(intent.current);
                    if (active && (!item.submenu || opened)) return;
                    const go = () => move(index, position - (latest.current[index]?.active ?? 0), true);
                    // On the way to an open submenu the pointer may cross other entries; wait a moment.
                    if (levels.length > index + 1) intent.current = window.setTimeout(go, 160);
                    else go();
                  }}
                  onClick={() => choose(index, item)}>
                  {Icon && <Icon size={15} aria-hidden="true" />}
                  <span className="pl-context-label">{item.label}
                    {item.blocked ? <small className="is-reason">{item.blocked}</small> : item.detail && !item.submenu && <small>{item.detail}</small>}</span>
                  {item.submenu && <><span className="pl-context-count">{item.detail}</span><ChevronRight size={14} aria-hidden="true" /></>}
                </div>
              </div>;
            })}
            {!items.length && <p className="pl-context-empty" role="presentation">
              {level.query ? "No matching steps." : level.menu.empty ?? "Nothing to choose here."}</p>}
          </div>
        </ScrollLock>
        {/* Every entry's text shares one cell, so the panel is as tall as the longest and stays put. */}
        {items.some((item) => item.help) && <div className="pl-context-help">
          {items.map((item, position) => item.help && <p key={item.key} data-active={position === level.active}
            id={position === level.active ? helpId : undefined}>{item.help}</p>)}
        </div>}
      </div>;
    })}
  </div>, document.body);
}

/** Wheel events step through entries; the list itself must not scroll with them. */
function ScrollLock({ children }: { children: ReactNode }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = element.current;
    if (!node) return;
    const block = (event: WheelEvent) => event.preventDefault();
    node.addEventListener("wheel", block, { passive: false });
    return () => node.removeEventListener("wheel", block);
  }, []);
  return <div ref={element} className="pl-context-scroll">{children}</div>;
}
