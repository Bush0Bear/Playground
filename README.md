# Playground

A space for **rough drafts** and a multitude of ideas & projects.

This is where things get drafted *before* they (maybe) graduate into their own
repositories. Nothing here is precious — it's a workbench, not a showroom.
Expect half-finished spikes, throwaway experiments, and the occasional idea
that earns its own home elsewhere.

## How it's organized

```
Playground/
├── ideas.md          # running backlog — capture ideas fast, sort later
├── drafts/           # active work; one folder per project/experiment
│   └── _template/    # copy this to start a new draft
└── archive/          # parked or retired drafts (kept for reference)
```

## Workflow

1. **Capture** — jot the idea in `ideas.md`. No commitment required.
2. **Draft** — when an idea has legs, copy `drafts/_template/` to
   `drafts/<your-project>/` and start building.
3. **Graduate or archive** — if a draft proves itself, spin it out into its own
   repository and leave a note here pointing to it. If it fizzles, move it to
   `archive/`.

## Conventions

- Each draft lives in its own folder under `drafts/` and owns a short `README.md`
  explaining what it is and its current status.
- Keep dependencies local to each draft where possible so experiments stay
  isolated.
- Status lives at the top of each draft's README: `idea`, `wip`, `paused`,
  `graduated`, or `archived`.
