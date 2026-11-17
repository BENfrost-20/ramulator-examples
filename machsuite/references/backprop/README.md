# Backprop reference

`check.data` is the reference supplied by
[@BENfrost-20](https://github.com/BENfrost-20) in the
[MachSuite integration](https://github.com/BENfrost-20/ramulator-examples/tree/363d3422ee753f72d27e50f2b2c0f45ea06788f9/machsuite/references/backprop).
It originates from `MachSuite_modified/backprop/backprop/check.data` in
`MachSuite_modified.zip`, used by the original benchmark integration from
[@jesunsahariar](https://github.com/jesunsahariar).

- Reference SHA-256: `dbc72d8ea7b1ee95b9cbac1788278d5e4418a7704976f43e57b1464827a27b57`
- Archive SHA-256: `fdd709dc35ad2b452f62d6bb4ea2e05d4a31891424eac76a3eddd6a2b73ff4c8`

The unchanged official kernel passes against this reference on the tested hosts
and fails against the official reference. The official input and reference remain
in the pinned source submodule; the recipe stages both reference files and
explicitly selects this one. No reference is regenerated during testing.

The checker rejects non-finite weights and biases and uses the upstream
numerical tolerance. This reference choice does not establish an independent
mathematical oracle for backprop.
