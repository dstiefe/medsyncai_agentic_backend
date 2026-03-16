"""
Device data models for MedSync AI Sales Simulation Engine.

Pydantic v2 models that match the devices.json schema exactly.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class Dimension(BaseModel):
    """Represents a physical dimension with multiple unit options."""

    inches: Optional[float] = None
    mm: Optional[float] = None
    french: Optional[float] = None


class LengthDimension(BaseModel):
    """Represents a length dimension with metric units."""

    cm: Optional[float] = None
    mm: Optional[float] = None


class DeviceCategory(BaseModel):
    """Represents a device category classification."""

    raw: str
    key: str
    display_name: str
    group: str
    role: str


class DeviceSpecifications(BaseModel):
    """Represents the technical specifications of a device."""

    inner_diameter: Dimension
    outer_diameter_distal: Dimension
    outer_diameter_proximal: Dimension
    length: LengthDimension


class DeviceCompatibility(BaseModel):
    """Represents compatibility parameters for a device."""

    wire_max_od: Dimension
    catheter_max_od: Dimension
    catheter_req_id: Dimension
    guide_min_id: Dimension


class SourceInfo(BaseModel):
    """Represents document source information."""

    has_doc: bool
    source_type: Optional[str] = None
    openai_id: Optional[str] = None
    local_path: Optional[str] = None
    s3_url: Optional[str] = None


class SpecPicSource(BaseModel):
    """Represents specification picture source information."""

    has_pic: Optional[bool] = None
    local_path: Optional[str] = None
    s3_url: Optional[str] = None


class WebpageSource(BaseModel):
    """Represents webpage source information."""

    file: Optional[str] = None
    local_path: Optional[str] = None


class DeviceSources(BaseModel):
    """Represents all available sources for a device."""

    ifu: SourceInfo
    fda: SourceInfo
    spec_pic: SpecPicSource
    webpage: WebpageSource


class Device(BaseModel):
    """Represents a medical device in the neurovascular stroke thrombectomy domain."""

    id: int = Field(..., description="Unique device identifier")
    manufacturer: str = Field(..., description="Device manufacturer name")
    device_name: str = Field(..., description="Full device name with specifications")
    product_name: str = Field(..., description="Product name")
    aliases: List[str] = Field(default_factory=list, description="Alternative names")
    category: DeviceCategory = Field(..., description="Device category classification")
    conical_category: str = Field(..., description="Conical category code (e.g., L0, L1)")
    fit_logic: str = Field(..., description="Logic used for compatibility (e.g., math)")
    logic_category: str = Field(
        ..., description="Logic category (e.g., sheath catheter)"
    )
    specifications: DeviceSpecifications = Field(..., description="Technical specs")
    compatibility: DeviceCompatibility = Field(
        ..., description="Compatibility requirements"
    )
    sources: DeviceSources = Field(..., description="Available source documents")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": 177,
                "manufacturer": "Stryker",
                "device_name": "Dash Hydrophilic Short Sheath (11 cm)",
                "product_name": "Dash Hydrophilic Short Sheath",
                "aliases": ["Dash Short Sheath", "Dash Sheath"],
                "category": {
                    "raw": "sheath",
                    "key": "sheath",
                    "display_name": "Sheath",
                    "group": "access",
                    "role": "access",
                },
                "conical_category": "L0",
                "fit_logic": "math",
                "logic_category": "sheath catheter",
            }
        }
