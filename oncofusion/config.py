"""Run presets are executable treatments, rather than labels on identical runs."""
from .schemas import Ablations, ROLES, RunConfig


def presets() -> dict[str, RunConfig]:
    configs = {"full": RunConfig()}
    for mode in ("single_direct", "single_tools", "single_iterative"):
        configs[mode] = RunConfig(mode=mode)
    configs["fixed_five"] = RunConfig(mode="fixed_five", ablations=Ablations(
        structured_board=False, external_verification=False, targeted_requery=False))
    configs["schema_repair"] = RunConfig(schema_retries=1)
    configs["all_generalist"] = RunConfig(delegated_roles=list(ROLES))
    configs["fixed_text"] = RunConfig(ablations=Ablations(
        structured_board=False, external_verification=False, targeted_requery=False))
    configs["adaptive"] = RunConfig(routing="adaptive")
    for feature in Ablations.model_fields:
        configs["without_" + feature] = RunConfig(ablations=Ablations(**{feature: False}))
    for role in ROLES:
        configs["delegate_" + role] = RunConfig(delegated_roles=[role])
    return configs
