# Friction taxonomy

Classify every deviation from the faithful documented path as one of:

- `docs`: missing, wrong, ambiguous, stale, or undiscoverable guidance;
- `dependency`: install, version, platform, or package incompatibility;
- `credential`: an expected credential/permission/claim is unavailable;
- `product`: API/UI behavior blocks or contradicts the documented path;
- `runner_environment`: execution image, network, queue, or provider failure;
- `sandbox`: policy or isolation prevents a safe action;
- `not_reached`: downstream step could not be tested after a prior blocker.

Record source step, observation, severity, evidence reference, faithful first
blocker, any workaround/deviation, smallest human-review-ready fix, and exact
next verification. Recovery does not erase the friction.
