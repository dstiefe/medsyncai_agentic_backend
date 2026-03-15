# Database Field Naming Convention

All specification fields follow this pattern:
```
specification_<measurement>_<unit>
```

## Diameter Fields

**Outer Diameter:**
```
specification_outer-diameter-distal_in
specification_outer-diameter-distal_mm
specification_outer-diameter-distal_F
specification_outer-diameter-proximal_in
specification_outer-diameter-proximal_mm
specification_outer-diameter-proximal_F
```

**Inner Diameter:**
```
specification_inner-diameter-distal_in
specification_inner-diameter-distal_mm
specification_inner-diameter-distal_F
specification_inner-diameter-proximal_in
specification_inner-diameter-proximal_mm
specification_inner-diameter-proximal_F
```

**Length:**
```
specification_length_cm
```

## Logic Category Field

**REQUIRED:** Every search must include a `logic_category` field to filter by device type.

```
logic_category
```

**Valid values:** `wire`, `stent`, `catheter`, `sheath`, `balloon`, `other`

**Format:** A space-separated string when multiple categories apply.
- Single category: `"wire"`
- Multiple categories: `"wire stent"`

**Mapping from `device_type`:**

| Input `device_type` | `logic_category` value |
|---------------------|------------------------|
| `"wire"` | `"wire"` |
| `"catheter"` | `"catheter"` |
| `"sheath"` | `"sheath"` |
| `"stent"` | `"stent"` |
| `"balloon"` | `"balloon"` |
| `null` or unknown | `"other"` |

## Unit Mapping

### Diameter Units

| Input Unit | Database Suffix |
|------------|-----------------|
| `in` | `_in` |
| `mm` | `_mm` |
| `Fr` or `F` | `_F` |

### Length Unit Conversion

Length is always stored in **centimeters (cm)** in the database. Convert as needed:

| Input Unit | Conversion |
|------------|------------|
| `cm` | Use value as-is |
| `mm` | Divide by 10 |
| `m` | Multiply by 100 |
| `in` | Multiply by 2.54 |

## Insufficient Information Summary

| Condition | Example Reason |
|-----------|----------------|
| No attributes provided | "For a [device_type], we need dimensions (OD, ID) and length." |
| Wire missing OD | "For a wire, we need the outer diameter." |
| Non-wire missing length | "For a [device_type], we also need the length." |
| Ambiguous context, only one diameter | "For a [device_type], we need both the OD and ID." |
| Device type is null | "We couldn't identify this device type." |