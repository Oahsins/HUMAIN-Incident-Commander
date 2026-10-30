"""The incident commander's arms. Every arm has the same signature (CONTRACT.md section 9):

    run_incident(adapter, *, budget_s=90.0, max_steps=40, model=None, log=None, seed=0,
                 mode="auto", confirm=None, **_) -> dict

    from ic.agent import load_arm
    result = load_arm("abcde")(adapter, model="anthropic:...")
"""

import functools

ARMS = ("abcde", "naive_verify", "fifo", "react")


def load_arm(name):
    """The run_incident function of one arm. KeyError for an arm that does not exist."""
    if name in ("abcde", "naive_verify", "fifo"):
        from ic.agent import abcde
        return functools.partial(abcde.run_incident, arm=name)
    if name == "react":
        from ic.agent import react
        return react.run_incident
    raise KeyError(f"no arm named {name!r}; arms: {', '.join(ARMS)}")
