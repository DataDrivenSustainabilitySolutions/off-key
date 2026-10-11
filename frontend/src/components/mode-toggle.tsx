import * as Primitive from "@radix-ui/react-dropdown-menu";
import { Check, Moon, Sun } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useTheme } from "@/components/theme-provider";

export function ModeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  return <DropdownMenu>
    <DropdownMenuTrigger asChild><button className="app-icon-button" aria-label="Theme" title="Theme">
      {resolvedTheme === "dark" ? <Moon size={17} /> : <Sun size={17} />}
    </button></DropdownMenuTrigger>
    <DropdownMenuContent className="app-popover app-menu" align="end" sideOffset={8}>
      <Primitive.RadioGroup value={theme ?? "system"} onValueChange={(value) => setTheme(value as "light" | "dark" | "system")}>
        {(["light", "dark", "system"] as const).map((value) => <Primitive.RadioItem key={value} value={value} className="app-menu-item">
          <span className="app-menu-icon"><Primitive.ItemIndicator><Check size={16} /></Primitive.ItemIndicator></span>
          {value.charAt(0).toUpperCase() + value.slice(1)}
        </Primitive.RadioItem>)}
      </Primitive.RadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>;
}
