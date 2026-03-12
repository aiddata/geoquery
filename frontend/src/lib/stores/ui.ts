import { writable } from "svelte/store";

export type SidebarPanel = "cart" | "help" | null;

export const sidebarOpen = writable(false);
export const sidebarPanel = writable<SidebarPanel>(null);

export function openSidebar(panel: SidebarPanel) {
  sidebarPanel.set(panel);
  sidebarOpen.set(true);
}

export function closeSidebar() {
  sidebarOpen.set(false);
}

export type Step = "map" | "search" | "review";

export const currentStep = writable<Step>("map");
