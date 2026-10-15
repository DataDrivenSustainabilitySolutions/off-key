import { useId } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type Theme } from "@/components/theme-provider";

const themes = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Follow system", icon: Monitor },
] as const satisfies ReadonlyArray<{ value: Theme; label: string; icon: typeof Sun }>;

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme();
  const id = useId();

  return (
    <fieldset className="app-settings-fieldset" aria-describedby={`${id}-help`}>
      <legend>Theme</legend>
      <p id={`${id}-help`} className="app-settings-help">
        Choose a light or dark appearance, or match your device’s settings.
      </p>
      <div className="app-settings-themes">
        {themes.map(({ value, label, icon: Icon }) => (
          <label key={value} className="app-settings-theme">
            <input type="radio" name={`${id}-theme`} value={value}
              checked={theme === value} onChange={() => setTheme(value)} />
            <span className="app-settings-theme-card">
              <span className="app-settings-theme-preview" data-theme={value} aria-hidden="true">
                <span className="app-settings-preview-sidebar"><i /><i /><i /></span>
                <span className="app-settings-preview-content"><i /><i /><i /></span>
              </span>
              <span className="app-settings-theme-label">
                <Icon size={16} aria-hidden="true" />
                <span>{label}</span>
                <span className="app-settings-theme-check" aria-hidden="true"><Check size={12} /></span>
              </span>
            </span>
          </label>
        ))}
      </div>
      <p className="app-settings-save-note">Changes apply immediately and are saved on this device.</p>
    </fieldset>
  );
}
