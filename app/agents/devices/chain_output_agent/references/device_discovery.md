# Device Discovery - Multiple Results (3+)

TASK: Present compatible devices found for the source device.

FORMAT: Use a markdown table for multiple results:

| Device | ID | OD | Length | Manufacturer |
|--------|-----|-----|--------|--------------|
| Headway 21 | 0.021" | 0.026" | 150cm | MicroVention |
| Phenom 21 | 0.021" | 0.028" | 150cm | Medtronic |

STRUCTURE:
1. Brief intro stating the source device requirements (1 sentence)
2. Neutral transition like: "The following meet these requirements:" or "Compatible options include:"
3. Markdown table with up to 10-15 options
4. Note total count if more exist: "There are X compatible devices in total."

MULTI-SIZE HANDLING FOR DISCOVERY:
- If the source device has multiple sizes, state the range: "The [Device] (depending on size) requires ID of X-Y inches"
- If only some sizes of the source device are compatible, note which ones

LANGUAGE RULES:
- Stay neutral and clinical - no marketing language
- NEVER use: "commonly used", "popular", "best", "recommended", "leading", "preferred", "top choices", "key options"
- NEVER imply one device or manufacturer is better than another
- USE: "compatible", "meet the requirements", "within specifications", "available options"
- List devices alphabetically by manufacturer or by specification, not by preference

# Device Discovery - Few Results (1-2)

TASK: Present compatible devices found for the source device.

FORMAT: Use inline prose for few results.

STRUCTURE:
1. Briefly state what the source device requires (ID range, length)
2. List the compatible devices with key specs inline
3. Keep it concise

MULTI-SIZE HANDLING:
- If the source device has multiple sizes with different requirements, present the full range

LANGUAGE RULES:
- Stay neutral and clinical - no marketing language
- NEVER use: "commonly used", "popular", "best", "recommended"
- USE: "compatible", "meet the requirements"