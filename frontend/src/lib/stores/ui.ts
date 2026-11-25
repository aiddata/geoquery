import { writable } from "svelte/store";

export type Step = "map" | "search" | "review";

export const currentStep = writable<Step>("map");
