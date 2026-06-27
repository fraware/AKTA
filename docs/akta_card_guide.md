# AKTA Card Guide

The AKTA Card is an institutional disclosure artifact summarizing how an AI-for-science system is deployed with respect to scientific action admissibility.

## Required fields

- System name, owner, and domain
- Deployment profile and maximum responsibility level
- Allowed, review-required, and blocked action types
- Evidence and validation thresholds
- Review process description
- Audit and recording policy
- Known failure modes
- Non-certification statement

## Validation

```bash
akta card validate examples/akta_card.json
```

## Purpose

The AKTA Card helps funders, journals, labs, and governance reviewers understand:

- What the system is authorized to do
- What requires review or authorization
- What evidence thresholds apply
- How AKTA Records are retained

## Non-certification

Every AKTA Card must include a non-certification statement. The card describes deployment characteristics; it is not a safety certification.
