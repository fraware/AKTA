# Scientific Authority Transfer

Scientific authority transfer occurs when an AI output changes what a scientific system is more likely to believe, test, modify, prioritize, execute, or publish.

## Examples

- A weak signal becomes the next experimental priority
- A literature summary becomes a recommendation for the current lab
- A protocol clarification changes the actual method
- A ranked list becomes resource allocation
- A plan becomes a robot-ready payload
- A multi-agent handoff hides where responsibility escalated

## AKTA response

AKTA makes authority transfer visible, classifiable, permissioned, reviewable, and reconstructable by:

1. Classifying the implied scientific action type (A0–A10)
2. Assigning a responsibility level (R0–R9)
3. Evaluating evidence and validation constraints
4. Applying deployment profile and domain overlay policy
5. Gating tool calls
6. Emitting an AKTA Record

## Multi-agent handoff rule

If responsibility escalates across a handoff chain, the final decision is evaluated at the highest responsibility level reached in the chain.
