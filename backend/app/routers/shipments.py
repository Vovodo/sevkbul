from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ShipmentCreateRequest, ShipmentCreateResponse,
    ShipmentProgressSchema, ShipmentLabelSchema,
)
from app.services.shipment_service import (
    create_shipment, get_shipment_progress, get_active_shipments
)
from app.services.lookup_cache import lookup_cache
from app.models import Shipment

router = APIRouter(prefix="/api/shipments", tags=["shipments"])


@router.post("/", response_model=ShipmentCreateResponse)
def create_new_shipment(req: ShipmentCreateRequest, db: Session = Depends(get_db)):
    try:
        result = create_shipment(db, req.reference.strip(), req.requested_quantity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ShipmentCreateResponse(
        shipment_id=result.shipment_id,
        reference=result.reference,
        requested_quantity=float(result.requested_quantity),
        pool_quantity=float(result.pool_quantity),
        label_count=result.label_count,
        fifo_group_count=result.fifo_group_count,
        insufficient_stock=result.insufficient_stock,
        remaining_unfulfilled=float(result.remaining_unfulfilled),
    )


@router.get("/active", response_model=list[ShipmentProgressSchema])
def list_active_shipments(db: Session = Depends(get_db)):
    return get_active_shipments(db)


@router.get("/{shipment_id}/progress", response_model=ShipmentProgressSchema)
def shipment_progress(shipment_id: int, db: Session = Depends(get_db)):
    try:
        return get_shipment_progress(db, shipment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{shipment_id}/labels", response_model=list[ShipmentLabelSchema])
def shipment_labels(shipment_id: int, db: Session = Depends(get_db)):
    pool = lookup_cache.get_pool(shipment_id)
    if not pool:
        shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
        if not shipment:
            raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")
        lookup_cache.load_shipment(db, shipment_id)
        pool = lookup_cache.get_pool(shipment_id)

    return [
        ShipmentLabelSchema(
            label=d["label"],
            reference=d["reference"],
            allocated_quantity=d["allocated_quantity"],
            total_quantity=d["total_quantity"],
            fifo_date=d["fifo_date"],
            fifo_group_date=d.get("fifo_group_date", d["fifo_date"][:10]),
            status=d["status"],
        )
        for d in pool.values()
    ]


@router.get("/", response_model=list[ShipmentProgressSchema])
def list_all_shipments(db: Session = Depends(get_db)):
    shipments = db.query(Shipment).order_by(Shipment.created_at.desc()).limit(50).all()
    return [get_shipment_progress(db, s.id) for s in shipments]
