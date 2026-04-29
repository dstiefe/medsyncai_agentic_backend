TASK: Validate a multi-device configuration (3+ devices).

CRITICAL - CHECK FOR N-1 SCENARIOS:
If NOT all requested devices can fit in a single configuration:
1. FIRST clearly state: "All X devices cannot be used in a single configuration."
2. EXPLAIN WHY - identify which devices conflict and the reason:
   - "Device A and Device B are both proximal sheaths - they serve the same role and cannot nest inside each other"
   - "Device X's OD (0.085") is larger than Device Y's ID (0.046") - they cannot connect"
3. THEN present the valid subset configurations as labeled options
4. Note which device is EXCLUDED in each option

MULTI-SIZE HANDLING FOR STACKS:
- If a device in the stack has multiple sizes, and compatibility varies by size:
  - State which sizes work and which don't
  - Example: "The Trevo NXT 3x32 and 4x28 sizes fit through Headway 21, but larger sizes (4x41, 6x37) require a larger microcatheter"
- When showing specs in tables, if sizes vary, show the range or note "varies by size"

EXAMPLE FOR N-1 SCENARIO:
"All 5 devices cannot be used in a single configuration. The Paragon 8F and Neuron MAX are both proximal access sheaths - these serve the same role and cannot nest inside each other.

Here are two valid 4-device configurations:

**Option A (excludes Neuron MAX):**
Trak 21 -> Vecta 46 -> Vecta 71 -> Paragon 8F

| Connection | Distal OD | Proximal ID | Status |
|------------|-----------|-------------|--------|
| Trak 21 -> Vecta 46 | 0.035" | 0.046" | Compatible |
| Vecta 46 -> Vecta 71 | 0.058" | 0.071" | Compatible |
| Vecta 71 -> Paragon 8F | 0.085" | 0.087" | Compatible |

**Option B (excludes Paragon 8F):**
Trak 21 -> Vecta 46 -> Vecta 71 -> Neuron MAX

Both configurations are valid options."

FORMAT FOR STANDARD STACK (all devices fit):
1. Natural opening stating the configuration works
2. Show device order: [distal] -> ... -> [proximal]
3. Markdown table showing each connection with dimensions
4. If incompatible, clearly mark which connection fails

| Connection | Distal OD | Proximal ID | Status |
|------------|-----------|-------------|--------|
| Solitaire -> Phenom 17 | 0.024" | 0.017" | Compatible |
| Phenom 17 -> Neuron MAX | 0.029" | 0.088" | Compatible |

GOOD OPENINGS (when all fit):
- "This configuration works..."
- "All devices are compatible in this order..."

GOOD OPENINGS (when n-1):
- "All X devices cannot be used in a single configuration..."
- "Not all devices can fit together because..."
- "These devices include two [sheaths/microcatheters/etc.] that serve the same role..."