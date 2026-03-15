# Domain Definitions

## Equipment Domain

Any query related to medical devices used in neurointerventional procedures.

### Indicators
- Named device products: Vecta, Solitaire, Neuron MAX, CAT 5, Penumbra, Headway, Arc, React, Sofia, etc.
- Device categories: catheter, microcatheter, intermediate catheter, aspiration catheter, sheath, guide catheter, wire, guidewire, microwire, stent retriever, stent, balloon, coil
- Specifications: OD, ID, outer diameter, inner diameter, length, French (Fr/F), working length, tip shape
- Compatibility: "work with", "compatible", "fit", "use with"
- Documentation: IFU, 510(k), FDA clearance, instructions for use
- Manufacturers: Medtronic, Stryker, MicroVention, Penumbra, Cerenovus, Balt, Integer, Phenox, Rapid Medical, Wallaby Medical
- Alphanumeric shorthand that could be device names: cat 5, c5, p7, r71, etc.
- Questions about what a device is, device specs, comparing devices, searching by dimensions

### Examples
- "What is a cat 5" → equipment
- "Can I use Vecta 46 with Neuron MAX?" → equipment
- "What microcatheters work with Solitaire?" → equipment
- "What is the OD of the Headway 21?" → equipment
- "Compare Vecta 46 and Vecta 71" → equipment
- "What does the IFU say about Solitaire?" → equipment
- "What Medtronic catheters are available?" → equipment

## Clinical Domain

Any query related to acute ischemic stroke (AIS) clinical management, treatment guidelines, or patient assessment.

### Indicators
- Patient parameters: NIHSS, ASPECTS, mRS, LKW (last known well), age with clinical context
- Stroke-specific terms: acute ischemic stroke, AIS, large vessel occlusion, LVO
- Treatment terms: IVT, EVT, thrombolysis, thrombectomy, alteplase, tenecteplase, tPA
- Occlusion locations used clinically: M1, M2, ICA, basilar (when discussing patient eligibility, not device compatibility)
- Clinical management: BP target, blood pressure management, antithrombotic therapy, anticoagulation
- Guidelines: AHA, ASA, guideline, recommendation, Class I, Level A, COR, LOE
- Complications: hemorrhagic transformation, reperfusion injury, contraindications
- Patient scenarios: "65yo, NIHSS 18, M1 occlusion, LKW 2h"

### Examples
- "65yo, NIHSS 18, M1 occlusion, LKW 2h" → clinical
- "What are the guidelines for EVT?" → clinical
- "What BP target for acute ischemic stroke?" → clinical
- "Is this patient eligible for IVT?" → clinical
- "What are the contraindications for thrombolysis?" → clinical

## Other Domain

Anything that is not about medical devices or AIS clinical guidelines.

### Examples
- "Hello" → other
- "What can you do?" → other
- "Thanks" → other
- "How do I manage ICH?" → other (not AIS-specific)
