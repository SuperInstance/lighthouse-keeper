primary_plane: 3
reads_from: [2, 3, 4, 5]
writes_to: [3]
floor: 2
ceiling: 5
compilers:
  - name: deepseek-chat
    from: 4
    to: 2
    locks: 7
reasoning: |
  Lighthouse-keeper is the fleet monitoring system operating at Plane 3 (JSON API).
  It observes the entire fleet stack from FLUX bytecode (2) through natural Intent (5),
  aggregating state and issuing structured alerts. As a monitor, it needs visibility
  into all execution layers but communicates via structured IR (3).

  Floor at 2 means it understands bytecode for deep observability (can disassemble
  and analyze FLUX instructions), but its outputs remain structured IR for reliable
  alerts and fleet coordination. The compiler from Domain Language (4) to Bytecode (2)
  enables analysis of skill patterns and behavioral detection.
