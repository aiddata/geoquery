import type { BoundaryPreset, BoundaryResult } from '#lib/api.js';

/**
 * The boundary sets a preset selects, from the full boundary list.
 *
 * List presets (`members`) take exactly the named sets that are available;
 * rule presets match source, level and tags (all of `tags`, at least one of
 * `any_tags`, none of `exclude_tags`). See backend/config/boundary_presets.yaml.
 */
export function resolvePreset(preset: BoundaryPreset, all: BoundaryResult[]): BoundaryResult[] {
	if (preset.members) {
		const byName = new Map(all.map((b) => [b.name, b]));
		return preset.members.map((name) => byName.get(name)).filter((b): b is BoundaryResult => !!b);
	}
	const tags = preset.tags ?? [];
	const anyTags = preset.any_tags ?? [];
	const excludeTags = preset.exclude_tags ?? [];
	return all.filter((b) => {
		const has = (t: string) => b.tags?.includes(t) ?? false;
		if (preset.source_name && b.source_name !== preset.source_name) return false;
		if (preset.group_class && b.group_class !== preset.group_class) return false;
		if (preset.group_level != null && b.group_level !== preset.group_level) return false;
		if (!tags.every(has)) return false;
		if (anyTags.length > 0 && !anyTags.some(has)) return false;
		if (excludeTags.some(has)) return false;
		return true;
	});
}
