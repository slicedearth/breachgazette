# Source semantics

Each source policy defines one unit of observation, threshold, population,
public window, coverage type, publication level, named-entity role,
revision behavior, licence state, attribution, correction process, and known
limitations.

Values additionally retain an origin and a state. Origin distinguishes source
observation, normalization, calculation, manual curation, and candidate
derivation. State distinguishes present, zero, null, missing, source omitted,
not applicable, estimated, unsupported, failed parsing, suppressed, and
intentionally excluded.

The public interface says “The source reports” because a published record is
evidence of a source statement, not independent verification. Source absence
is represented as unsupported or out of window, never “safe” or “no breaches.”
