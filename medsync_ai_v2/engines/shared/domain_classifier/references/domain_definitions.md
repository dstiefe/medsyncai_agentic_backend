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

## Sales Domain

Any query related to medical device sales training, sales simulations, meeting preparation, competitive positioning, or sales rep performance.

### Indicators
- Sales simulation: "practice a sales call", "simulate a meeting", "role play", "sales scenario"
- Meeting prep: "meeting prep", "intelligence brief", "pre-call", "prepare for meeting with"
- Knowledge assessment: "quiz me", "test my knowledge", "assessment", "certification"
- Competitive positioning: "competitive advantage", "how to sell against", "differentiators", "objection handling"
- Sales vocabulary: "rep", "sales rep", "territory", "physician meeting", "product pitch", "closing"
- Device sales context: "sell to", "pitch", "convince", "value proposition", "ROI"
- Rep tracking: "my scores", "my performance", "training progress", "dashboard"
- Physician dossier: "dossier", "physician profile", "CMS data", "case volume", "doctor intel"
- Field intel: "field debrief", "competitive trends", "win/loss"

### Examples
- "Practice a sales call with Dr. Chen" → sales
- "Generate a meeting prep brief for a Penumbra doctor" → sales
- "Quiz me on device specifications" → sales
- "How do I handle the objection about cost?" → sales
- "Show me my training scores" → sales
- "Create a dossier for Dr. Rodriguez" → sales

## Other Domain

Anything that is not about medical devices, AIS clinical guidelines, or sales training.

### Examples
- "Hello" → other
- "What can you do?" → other
- "Thanks" → other
- "How do I manage ICH?" → other (not AIS-specific)
