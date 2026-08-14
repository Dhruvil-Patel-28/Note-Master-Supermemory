from fastapi import APIRouter, HTTPException

from ..guardrails import pin

router = APIRouter(prefix="/pin", tags=["pin"])

_MIN_LEN = 4
_MAX_LEN = 32


def _validate(pin_value: str) -> None:
    if not (_MIN_LEN <= len(pin_value) <= _MAX_LEN):
        raise HTTPException(
            status_code=422,
            detail=f"pin must be {_MIN_LEN}-{_MAX_LEN} characters",
        )


@router.get("/status")
def pin_status():
    return {"set": pin.is_set()}


@router.post("/set")
def pin_set(payload: dict):
    pin_value = payload.get("pin", "")
    _validate(pin_value)
    if pin.is_set():
        raise HTTPException(status_code=409, detail="pin already set")
    pin.set_pin(pin_value)
    return {"ok": True}


@router.post("/change")
def pin_change(payload: dict):
    old_pin, new_pin = payload.get("old_pin", ""), payload.get("new_pin", "")
    _validate(new_pin)
    if not pin.is_set() or not pin.verify_pin(old_pin):
        raise HTTPException(status_code=401, detail="invalid pin")
    pin.set_pin(new_pin)
    return {"ok": True}


@router.post("/verify")
def pin_verify(payload: dict):
    pin_value = payload.get("pin", "")
    if not pin.verify_pin(pin_value):
        raise HTTPException(status_code=401, detail="invalid pin")
    return {"token": pin.issue_token()}


@router.delete("")
def pin_delete(payload: dict = None):
    payload = payload or {}
    pin_value = payload.get("pin", "")
    if pin.is_set() and not pin.verify_pin(pin_value):
        raise HTTPException(status_code=401, detail="invalid pin")
    pin.clear_pin()
    return {"ok": True}