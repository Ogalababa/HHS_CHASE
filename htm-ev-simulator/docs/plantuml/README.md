# PlantUML diagrams

## Class diagram

- **File:** [`class_diagram.puml`](class_diagram.puml)
- **Scope:** Main types under `src/backend/core` (domain, ports, services, strategies) plus key infrastructure adapters and one frontend DTO. Omits script-only entrypoints and function-only report helpers.

### How to render

1. Install [PlantUML](https://plantuml.com/download) (needs Java) or use the [PlantUML extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml) in VS Code / Cursor.
2. From this directory:

```bash
plantuml class_diagram.puml
```

This produces `class_diagram.png` (and/or SVG depending on your PlantUML setup).

3. Or use the [PlantUML Web Server](https://www.plantuml.com/plantuml/uml/) and paste the `.puml` contents.

### Layout notes

- Packages are named by architectural role (domain / ports / services / adapters), not always 1:1 with Python import paths.
- `..|>` = structural implementation (`Protocol` / ABC in code).
- `..>` = dependency / use.
- `*--` / `o--` = composition / aggregation style ownership.
