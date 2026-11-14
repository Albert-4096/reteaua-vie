import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarHeader,
  SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar";
import { NAV } from "./parts";

export function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <rect width="24" height="24" rx="6" className="fill-primary" />
        <path d="M5 15.5h4.5l2.5-7 2.5 7H19" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-tight">Rețeaua Vie</div>
        <div className="text-[11px] text-muted-foreground">Primăria Timișoara · STPT</div>
      </div>
    </div>
  );
}

export function AppSidebar({ active, counts }: { active: string; counts: Record<string, number> }) {
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="h-14 justify-center border-b">
        <Logo />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu className="gap-1">
              {NAV.map((n) => (
                <SidebarMenuItem key={n.id}>
                  <SidebarMenuButton isActive={n.id === active} tooltip={n.label} className="h-10">
                    <n.icon />
                    <div className="flex flex-col leading-tight">
                      <span className="font-medium">{n.label}</span>
                      <span className="text-[11px] text-muted-foreground">{n.hint}</span>
                    </div>
                  </SidebarMenuButton>
                  {counts[n.id] ? <SidebarMenuBadge className="tnum">{counts[n.id]}</SidebarMenuBadge> : null}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t p-3 text-[11px] leading-relaxed text-muted-foreground group-data-[collapsible=icon]:hidden">
        Orar SMTT GTFS 4.31 · vehicule din API-ul Primăriei, la 15 s
      </SidebarFooter>
    </Sidebar>
  );
}
