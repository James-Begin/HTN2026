"""Claim-equivalence evaluation: the gate between a local checkpoint and Baseten.

Nothing in this package trains, and nothing touches a GPU unless the local scorer
is explicitly asked for with CLAIMTRACE_ALLOW_GPU=1 set.
"""
