# Attributes to Extract

| Attribute | Key | Description | Example Values |
|-----------|-----|-------------|----------------|
| Outer Diameter | `OD` | Outer diameter | 0.014", 0.017", 5Fr, 6mm |
| Inner Diameter | `ID` | Inner diameter | 0.021", 0.068", 6Fr |
| Length | `length` | Working/usable length | 100cm, 150cm, 200cm, 1500mm |
| Size | `size` | Generic size (French, mm) when OD/ID is unclear | 5Fr, 6Fr, 4mm |

Each attribute has a `value` (number) and `unit` (string).

## Units

| Unit | Format |
|------|--------|
| Inches | `"in"` — values like 0.014, 0.017, 0.021, 0.068, 0.074 |
| French | `"Fr"` — values like 4, 5, 6, 7, 8, 9 |
| Millimeters | `"mm"` — values like 2, 3, 4, 5, 6 |
| Centimeters | `"cm"` — values like 100, 115, 125, 132, 150, 200 |

## How to Determine OD vs ID vs Size

### Wires
- Decimal inches (0.014", 0.017", 0.018") → **always OD**
- Wires don't have an ID

### Catheters
- If user says "ID" or "inner diameter" → `ID`
- If user says "OD" or "outer diameter" → `OD`
- French size without specifying OD/ID → `size` (let downstream agent figure it out)
- Small decimals like .021", .027" on microcatheters → likely `ID`
- Larger decimals like .068", .074", .088" on guide/intermediate catheters → likely `ID`
- If ambiguous, use `size`

### Sheaths
- French size is typically **OD** for sheaths
- If user says "ID" → `ID`

### Stents / Balloons
- mm values (4mm, 6mm) → typically `OD` (deployed diameter)
- Length in mm (20mm, 30mm) → `length`
