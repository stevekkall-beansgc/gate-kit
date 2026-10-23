"""Exact, reviewed checker adoption delta for historical workflow proofs."""
OLD_VERSION = "v0.4.4"
NEW_VERSION = "v0.7.6"
OLD_SOURCE = "69ebc139280b5c3a1d7490399c6534be72ef2b76f4569ab3427c49996d87762f"
NEW_SOURCE = "8ff1f344a18206441829791c55fd7fd60176aec170a7445aad93c0cf5e61dd4c"
OLD_ADAPTED = "33d13dd1803674629333e898a64355efd068c76da8bc1db5e91fb2a0fb6d9741"
NEW_ADAPTED = "3d035d1d969e52ce516c4cae0cf731bae3d739157c80cde96ec0f9be690103aa"


def before_gate_runtime(workflow):
    for old, new in (
            ("inputs.repo == 'qa-kit' && '3.12'",
             "(inputs.repo == 'qa-kit' || inputs.repo == 'gate-kit') && '3.12'"),
            ("Select QA Kit caller Python 3.12", "Select QA and Gate Kit caller Python 3.12"),
            ("if: inputs.repo == 'qa-kit' && inputs.runner == 'beans-mac'",
             "if: (inputs.repo == 'qa-kit' || inputs.repo == 'gate-kit') && inputs.runner == 'beans-mac'")):
        if workflow.count(new) != 1:
            raise AssertionError("expected one scoped Gate caller runtime change")
        workflow = workflow.replace(new, old, 1)
    return workflow


def before_checker_adoption(workflow):
    for old, new in (("ref: " + OLD_VERSION, "ref: " + NEW_VERSION),
                     (OLD_SOURCE, NEW_SOURCE), (OLD_ADAPTED, NEW_ADAPTED)):
        if workflow.count(new) != 1:
            raise AssertionError("expected one reviewed checker selection/hash")
        workflow = workflow.replace(new, old, 1)
    return workflow


def before_workflow_adoption(workflow):
    workflow = before_gate_runtime(workflow)
    workflow = before_checker_adoption(workflow)
    for addition in (
            " || (inputs.repo == 'beanlabs' || inputs.repo == 'agents') && 'v0.7.10'",
            "inputs.repo == 'beanlabs' && '3.14' || ",
            " || (inputs.repo == 'beanlabs' && inputs.runner != 'beans-mac')"):
        if workflow.count(addition) != 1:
            raise AssertionError("expected one scoped setup cohort/runtime addition")
        workflow = workflow.replace(addition, "", 1)
    return workflow
