# C11 — Safe Offline Reinforcement Learning

RL is offline only. The historical or licensed behavior dataset defines support; proposed actions outside support are rejected or assigned abstention. No production or broker environment is an exploration sandbox.

State, action, reward and constraints are versioned. Reward separates return, risk, cost, capacity and operational penalties and cannot be modified by the candidate policy.

Evaluation uses multiple off-policy estimators, uncertainty intervals, behavior-cloning and simple-policy baselines, temporal holdouts, regime tests and stress. Disagreement or weak effective sample size blocks promotion.

Policies remain challengers until they pass historical holdout and subsequent shadow/paper gates. A policy cannot read evaluator internals or hidden holdouts, change its reward or promote itself.
