# AKTA Limitations

AKTA v0.1 is a reference kernel for scientific action admissibility. It explicitly does not:

- Decide scientific truth or correctness
- Replace evidence retrieval or scientific report generation (see VSA)
- Replace formal runtime authorization (see PF-Core)
- Replace release packaging and verification (see PCS-Core)
- Certify autonomous labs or safety compliance
- Replace EHS, IRB, biosafety, chemical safety, clinical review, or legal compliance
- Support fully autonomous scientific operation (P7 is taxonomy-only)
- Guarantee model truthfulness, tool honesty, or reviewer competence

## Trusted boundary assumptions

AKTA v0.1 assumes:

- Input context is provided honestly or marked uncertain
- Tool registry correctly describes tool effects
- Deployment profile is correctly configured
- Domain overlay is reviewed before deployment
- Runtime harness enforces AKTA decisions

## Non-certification

The AKTA Card describes system deployment characteristics. It is not a safety certification.
