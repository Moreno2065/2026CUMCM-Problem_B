"""Stage A: change observation state, keep production action selection."""
from learned_search.scheduler import LearnedSearchScheduler


class ConstraintSearchScheduler(LearnedSearchScheduler):
    def __init__(self, mode="Q3", **kwargs):
        if mode != "Q3":
            raise ValueError("constraint-search currently supports Q3 only")
        super().__init__(mode, **kwargs)

    def initialize_knowledge(self, ks):
        from constraint_search.state import ConstrainedChannelState
        if any(ch.observations for ch in ks.channels.values()):
            raise ValueError("install constrained state before the first action")
        ks.channels = {
            cid: ConstrainedChannelState(cid, mode=ks.mode,
                                        q4_certificate_layout=ks.q4_certificate_layout)
            for cid in ks.channels
        }
