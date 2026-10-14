Convert this issue into a compact implementation acceptance checklist. Do not write code, invoke tools, or propose a patch.

Issue:
{problem_description}

Hints, if supplied:
{hints?}

Return at most five bullets, prioritizing caller-visible behavior:
- Inputs and boundary cases the requested change must handle.
- Returned values, normalization, and observable side effects.
- Failure behavior: exception class, messages, status, headers, or response shape explicitly specified by the issue.
- Relevant sibling entry points and existing behavior that must remain compatible.
- One bounded verification scenario that distinguishes the requested behavior from merely accepting the input or avoiding a crash.

Do not invent exact messages, values, APIs, or requirements. Mark anything not specified as an uncertainty for the coder to resolve from existing repository conventions. Keep the entire checklist under 180 words.
