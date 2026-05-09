# Wire Resolution Rules

For wires:
- `OD` attribute → outer diameter (apply to both distal and proximal unless specified)
- `size` attribute with unit `in` → treat as outer diameter
- `length` attribute → length field
- Wires do NOT require length to search (length is optional for wires)
- Wires only need OD to search

## Distal/Proximal Logic

- If the `raw` text specifies **"distal"** → only set the distal field
- If the `raw` text specifies **"proximal"** → only set the proximal field
- If **neither** is specified → assume the value applies to **BOTH** distal and proximal

# Non-Wire Device Resolution Rules (Catheters, Stents, Sheaths, etc.)

For non-wire devices, you must determine which diameter(s) are needed based on:
1. What attributes were provided in the input
2. The context from `original_question`

## What Attributes Were Provided?

| Provided Attributes | Action |
|--------------------|--------|
| Both `OD` and `ID` | Use both as provided |
| Only `OD` | Check context to see if ID is also needed |
| Only `ID` | Check context to see if OD is also needed |
| Only `size` (Fr) | Determine from context if it's OD, ID, or both |

## Contextual Logic (when only one diameter is provided)

| Context in Question | What the single dimension represents |
|---------------------|-------------------------------------|
| Device is **fitting into** another device | **OD** (sufficient) |
| Something is **fitting inside** the device | **ID** (sufficient) |
| Ambiguous relationship ("works with", "compatible") | Need **BOTH** - mark as insufficient |
| Sequence/order questions | Need **BOTH** - mark as insufficient |

## Keywords to Identify Relationship

**Device is going INTO something (OD is sufficient):**
- "fit into", "fits into", "fitting into"
- "insert into", "go into", "goes into"
- "inside of", "within"
- "through" (when device is passing through another)

**Something is going INTO the device (ID is sufficient):**
- "fit inside", "fits inside"
- "accepts", "can accommodate"
- "what fits in", "what goes in"

**Ambiguous / Both needed:**
- "works with", "compatible with"
- "can I use X with Y"
- "use together", "combine"
- "sequence", "order", "correct order"
- No clear directional relationship stated

## Length Requirement for Non-Wire Devices

**Length is REQUIRED for non-wire device searches.** If length is not provided in `attributes`, set `has_info: false`.