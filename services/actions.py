from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

class DeviceAction(BaseModel):
    type: Literal["TORCH_ON", "TORCH_OFF", "OPEN_APP", "OPEN_SETTINGS", "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE", "GET_BATTERY", "NONE"] = Field(
        description="The action type to perform."
    )
    target: Optional[str] = Field(None, description="The target for the action (e.g., 'youtube', 'wifi').")
    extra: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Any extra parameters.")

class BrainResponse(BaseModel):
    reply: str = Field(description="Natural spoken response for the user as J.A.R.V.I.S.")
    action: Optional[DeviceAction] = Field(None, description="The system action to execute, or null if purely conversational.")
