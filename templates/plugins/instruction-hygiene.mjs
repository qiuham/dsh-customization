export const name = "instruction-hygiene";
export const inject = ["systemPrompt"];

const PRIMARY = "infinite-gen-4:global-system-prompt";
const REINFORCE = "infinite-gen-4:dual-layer-reinforce";

export function removeExactDuplicateReinforcement(assembly) {
  if (!Array.isArray(assembly?.sections)) return assembly;
  const primary = assembly.sections.find((section) => section?.name === PRIMARY);
  const reinforce = assembly.sections.find((section) => section?.name === REINFORCE);
  if (!primary || !reinforce || primary.text !== reinforce.text) return assembly;
  return {
    ...assembly,
    sections: assembly.sections.filter((section) => section !== reinforce),
  };
}

export function apply(ctx) {
  ctx.on("system-prompt/assemble", async (_assembly, _context, next) =>
    removeExactDuplicateReinforcement(await next()),
  );
}
