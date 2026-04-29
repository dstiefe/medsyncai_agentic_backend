# Worked Examples

### Example 1: Two fragments that are ONE device
**Question:** "will a 100cm wire that is .014" work with a trak 21"
**Fragments:** ["100cm wire", "0.014\" wire"]
```json
{
  "generic_devices": [
    {
      "raw": "100cm .014\" wire",
      "device_type": "wire",
      "attributes": {
        "OD": {"value": 0.014, "unit": "in"},
        "length": {"value": 100, "unit": "cm"}
      }
    }
  ]
}
```

### Example 2: Two separate devices
**Question:** "can I use a .014 wire and a 6Fr sheath with Neuron Max"
**Fragments:** [".014 wire", "6Fr sheath"]
```json
{
  "generic_devices": [
    {
      "raw": ".014\" wire",
      "device_type": "wire",
      "attributes": {
        "OD": {"value": 0.014, "unit": "in"}
      }
    },
    {
      "raw": "6Fr sheath",
      "device_type": "sheath",
      "attributes": {
        "size": {"value": 6, "unit": "Fr"}
      }
    }
  ]
}
```

### Example 3: One device with many specs
**Question:** "will a 5Fr 150cm catheter with .058\" ID fit into the Neuron Max"
**Fragments:** ["5Fr catheter", "150cm catheter", ".058\" ID catheter"]
```json
{
  "generic_devices": [
    {
      "raw": "5Fr 150cm .058\" ID catheter",
      "device_type": "catheter",
      "attributes": {
        "OD": {"value": 5, "unit": "Fr"},
        "ID": {"value": 0.058, "unit": "in"},
        "length": {"value": 150, "unit": "cm"}
      }
    }
  ]
}
```

### Example 4: No attributes at all
**Question:** "can I use a microcatheter with the Neuron Max?"
**Fragments:** ["microcatheter"]
```json
{
  "generic_devices": [
    {
      "raw": "microcatheter",
      "device_type": "catheter",
      "attributes": {}
    }
  ]
}
```
