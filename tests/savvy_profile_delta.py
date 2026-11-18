"""Remove only the separately proven Savvy manifest selection for older proofs."""
ADDITION = "inputs.repo == 'savvy-proto' && 'v0.9.0' || "
def before_savvy(workflow):
    if ADDITION not in workflow: return workflow
    if workflow.count(ADDITION) != 1: raise AssertionError('Savvy delta changed')
    return workflow.replace(ADDITION, '', 1)
