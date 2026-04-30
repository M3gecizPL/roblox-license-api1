from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class LicenseCheck(BaseModel):
    product_id: str
    creator_type: str
    creator_id: int
    universe_id: int
    place_id: int | None = None
    job_id: str | None = None


@app.get("/")
def home():
    return {
        "ok": True,
        "message": "License API działa"
    }


@app.post("/license/check")
def check_license(data: LicenseCheck):
    print("License check:", data)

    allowed = (
        data.product_id == "testowy_system"
        and data.creator_type in ["User", "Group"]
        and data.creator_id == 3673362474
    )

    if allowed:
        return {
            "ok": True,
            "active": True,
            "reason": "LICENSE_ACTIVE"
        }

    return {
        "ok": True,
        "active": False,
        "reason": "NO_ACTIVE_LICENSE"
    }