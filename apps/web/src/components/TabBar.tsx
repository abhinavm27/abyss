import { House, MessageCircleQuestion, ShieldCheck } from "lucide-react";

export type Tab = "home" | "ask" | "plan";

const TABS: { id: Tab; label: string; icon: typeof House }[] = [
  { id: "home", label: "Home", icon: House },
  { id: "ask", label: "Ask", icon: MessageCircleQuestion },
  { id: "plan", label: "Plan", icon: ShieldCheck },
];

/** Persistent bottom navigation.
 *
 * Three tabs, not four. Coverage is a reference list reachable from Plan —
 * giving it equal billing with the thing people came to do would pad the
 * navigation to fill it.
 *
 * The bar absorbs the bottom safe-area inset itself, so screens above it only
 * need to clear its height. */
export function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
    >
      <ul className="mx-auto flex w-full max-w-md">
        {TABS.map(({ id, label, icon: Icon }) => {
          const current = id === active;
          return (
            <li key={id} className="flex-1">
              <button
                onClick={() => onChange(id)}
                aria-current={current ? "page" : undefined}
                className={`flex w-full flex-col items-center gap-1 py-2.5 transition-colors ${
                  current ? "text-primary" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="h-5 w-5" strokeWidth={current ? 2.4 : 1.8} aria-hidden />
                <span className="text-xs font-medium">{label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Height of the bar itself, excluding the safe-area inset it absorbs. */
export const TAB_BAR_HEIGHT = "4.25rem";

/** Whether a string names a tab. The URL hash is user-editable, so it is
 *  validated against the same list the bar renders rather than a second copy. */
export const isTab = (s: string): s is Tab => TABS.some((t) => t.id === s);
