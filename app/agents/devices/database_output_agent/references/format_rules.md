# Database Output Format Rules

## Single Device (Inline Prose)

Use natural sentences, no table needed:
"The Headway 21 has an inner diameter of 0.021", outer diameter of 0.026", and length of 150cm."

## Two Devices (Comparison Table)

Use a side-by-side comparison table:

| Spec | Device A | Device B |
|------|----------|----------|
| ID | 0.021" | 0.017" |
| OD | 0.026" | 0.029" |
| Length | 150cm | 150cm |
| Manufacturer | MicroVention | Medtronic |

## Multiple Devices (3+) - Use Table

Use a markdown table to display results:

| Device | ID | OD | Length | Manufacturer |
|--------|-----|-----|--------|--------------|
| Headway 21 | 0.021" | 0.026" | 150cm | MicroVention |
| Phenom 21 | 0.021" | 0.028" | 150cm | Medtronic |

- Show up to 15 devices in the table
- Brief intro sentence stating total count
- If more than 15, note that additional options exist

## No Results

Explain that no devices matched the criteria and suggest alternatives if possible.