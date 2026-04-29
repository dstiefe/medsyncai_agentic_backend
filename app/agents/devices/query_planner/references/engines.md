## Available Engines

### database_engine
Queries a structured database of medical devices. Best for:
- Filtering devices by attributes (manufacturer, category, specs)
- Looking up device specifications
- Finding devices matching criteria

Actions:
- **filter_by_spec**: Filter devices by category and/or attribute filters
  - category: "catheter", "microcatheter", "wire", "sheath", "stent_retriever", "intermediate_catheter", "aspiration", "guide_catheter"
  - filters: [{"field": "manufacturer", "operator": "contains", "value": "Medtronic"}, {"field": "ID_in", "operator": ">=", "value": 0.021}]
- **get_device_specs**: Look up specs for specific device IDs
- **find_compatible**: Find devices compatible at a single connection point

### chain_engine
Evaluates full compatibility chains between multiple devices. Best for:
- Checking if Device A works with Device B (or through Device C)
- Building and testing complete device stacks (L0→L1→L2→L3→L4→L5)
- Multi-device compatibility with mathematical evaluation

Takes pre-resolved devices (name → IDs + conical_category) and tests all junctions.

### vector_engine
Searches IFU/510(k) document chunks using semantic search. Best for:
- IFU (Instructions for Use) questions
- 510(k) clearance information
- Manufacturer instructions, indications, contraindications
- Deployment procedures, warnings, guidelines from official documents

Actions:
- **search_documents**: Semantic search over IFU/510(k) vector store
  - Uses device IDs from named_devices for metadata filtering
  - Falls back to pure semantic search if no device IDs available